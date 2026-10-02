"""Menguji skrip registrasi di release.yml terhadap GONSU dan GitHub tiruan.

Skripnya hidup di dalam workflow, bukan di berkas tersendiri: workflow yang
dipanggil dari repo lain hanya membawa dirinya, tidak membawa isi repo ini.
Test ini mengambilnya dari sana dan menjalankannya apa adanya, sehingga yang
diuji adalah yang benar-benar berjalan saat rilis.

    python3 -m unittest discover -s tests -v
"""

import base64
import hashlib
import http.server
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

DIGEST = "sha256:" + "1e" * 32
COMMIT = "e0f4ac50477f4beac2a34109291eb2a3dece59a2"
REPORT = b'{"SchemaVersion":2,"Results":[]}'


def register_script():
    """Mengambil isi `run` langkah berid `register` dari workflow."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "id: register")
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip())
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"


class Platform:
    """GONSU dan penerbit bukti GitHub tiruan, dalam satu server.

    `states` adalah jawaban berturut-turut atas pertanyaan tentang keadaan
    tanda tangan; jawaban terakhir diulang.
    """

    def __init__(self, states=("pending", "signed"), register=(201, None), publish=(200, None),
                 failure_reason=""):
        self.states = list(states)
        self.register = register
        self.publish = publish
        self.failure_reason = failure_reason
        self.audiences = []
        self.requests = []

        platform = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path.startswith("/oidc"):
                    audience = self.path.split("audience=", 1)[1]
                    platform.audiences.append(audience)
                    if self.headers["Authorization"] != "bearer permintaan":
                        return self.reply(401, {})
                    return self.reply(200, {"value": "bukti-%d" % len(platform.audiences)})

                platform.requests.append(("GET", self.path, self.headers["Authorization"], None))
                state = platform.states.pop(0) if len(platform.states) > 1 else platform.states[0]
                if isinstance(state, int):
                    return self.reply(state, {"error": {"message": "galat tiruan"}})
                signing = {"state": state}
                if state == "failed":
                    signing["failure_reason"] = platform.failure_reason
                self.reply(200, {
                    "id": "rel_1", "version": "1.2.0", "status": "staged", "signing": signing,
                    "artifacts": [{"digest": DIGEST, "signature_status": "verified", "scan_status": "passed"}],
                })

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                platform.requests.append(("POST", self.path, self.headers["Authorization"], body))
                if self.path == "/internal/v1/releases":
                    status, payload = platform.register
                    return self.reply(status, payload or {
                        "id": "rel_1", "version": body["version"], "channel": "stable",
                        "status": "staged", "signing": {"state": "pending"}})
                status, payload = platform.publish
                self.reply(status, payload or {"id": "rel_1", "status": "published"})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RegisterScript(unittest.TestCase):
    def run_script(self, platform, **overrides):
        with tempfile.TemporaryDirectory() as temp:
            pathlib.Path(temp, "scan.json").write_bytes(REPORT)
            summary = pathlib.Path(temp, "summary.md")
            env = {
                "PATH": os.environ["PATH"],
                "RUNNER_TEMP": temp,
                "GITHUB_STEP_SUMMARY": str(summary),
                "GITHUB_SHA": COMMIT,
                "ACTIONS_ID_TOKEN_REQUEST_URL": platform.url + "/oidc?api-version=2.0",
                "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "permintaan",
                "API_URL": platform.url + "/",
                "TRIVY_VERSION": "0.74.0",
                "PRODUCT_CODE": "garment",
                "VARIANT_CODE": "web",
                "VERSION": "1.2.0",
                "CHANGELOG": "feat: sesuatu\n\nbadan pesan",
                "IMAGE": "registry.gonsu.cloud/products/garment-web",
                "DIGEST": DIGEST,
                "GONSU_RELEASE_POLL_INTERVAL": "0.01",
                "GONSU_RELEASE_SIGNING_TIMEOUT": "2",
            }
            env.update(overrides)
            for name in [name for name, value in env.items() if value is None]:
                del env[name]
            result = subprocess.run([sys.executable, "-c", register_script()], env=env,
                                    capture_output=True, text=True, timeout=60)
            result.summary = summary.read_text(encoding="utf-8") if summary.exists() else ""
            return result

    def platform(self, **kwargs):
        platform = Platform(**kwargs)
        self.addCleanup(platform.close)
        return platform

    def test_mendaftar_menunggu_lalu_menerbitkan(self):
        platform = self.platform(states=("pending", "pending", "signed"))
        result = self.run_script(platform)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        method, path, authorization, body = platform.requests[0]
        self.assertEqual((method, path), ("POST", "/internal/v1/releases"))
        self.assertEqual(authorization, "Bearer bukti-1")
        self.assertEqual(base64.b64decode(body["scan_report"]), REPORT)
        self.assertEqual(body["scanner"], "trivy 0.74.0")
        self.assertEqual(body["source_revision"], COMMIT)
        self.assertEqual(body["version"], "1.2.0")
        self.assertEqual(body["artifacts"], [{
            "kind": "oci", "platform": "linux", "architecture": "amd64",
            "location": "registry.gonsu.cloud/products/garment-web", "tag": "1.2.0", "digest": DIGEST,
        }])
        # Pipeline tidak mengklaim hasil pemeriksaan apa pun.
        self.assertNotIn("signature_status", json.dumps(body))
        self.assertNotIn("scan_status", json.dumps(body))

        self.assertEqual([request[:2] for request in platform.requests[1:]], [
            ("GET", "/internal/v1/releases/rel_1"),
            ("GET", "/internal/v1/releases/rel_1"),
            ("GET", "/internal/v1/releases/rel_1"),
            ("POST", "/internal/v1/releases/rel_1/status"),
        ])
        self.assertEqual(platform.requests[-1][3], {"status": "published"})
        self.assertIn("Rilis 1.2.0 terbit", result.summary)

    def test_audience_mengikat_bukti_ke_image_dan_laporan(self):
        platform = self.platform()
        self.run_script(platform)
        # Bentuk ini diperiksa GONSU; mengubahnya membuat setiap rilis ditolak.
        want = "gonsu-release:%s:%s" % (DIGEST, hashlib.sha256(REPORT).hexdigest())
        self.assertEqual(platform.audiences[0], want.replace(":", "%3A"))
        # Bukti untuk bertanya tidak menyebut image mana pun, dan dipakai ulang.
        self.assertEqual(platform.audiences[1:], ["gonsu-release"])

    def test_bukti_disamarkan_sebelum_dipakai(self):
        platform = self.platform()
        result = self.run_script(platform)
        self.assertIn("::add-mask::bukti-1", result.stdout)
        self.assertIn("::add-mask::bukti-2", result.stdout)

    def test_registrasi_ditolak(self):
        platform = self.platform(register=(403, {"error": {
            "code": "forbidden", "message": "Repository ini bukan milik akun GitHub yang dipercaya platform.",
            "request_id": "req_9"}}))
        result = self.run_script(platform)
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::Registrasi rilis ditolak GONSU (403). Repository ini bukan milik", result.stdout)
        self.assertIn("(request_id req_9)", result.stdout)
        self.assertEqual(len(platform.requests), 1)

    def test_galat_validasi_menyebut_field(self):
        platform = self.platform(register=(400, {"error": {
            "message": "Manifest rilis tidak valid. Periksa detail per field.",
            "details": [{"field": "product_code", "message": "produk tidak ditemukan"}]}}))
        result = self.run_script(platform)
        self.assertEqual(result.returncode, 1)
        self.assertIn("product_code: produk tidak ditemukan", result.stdout)

    def test_tanda_tangan_ditolak_tidak_menerbitkan(self):
        platform = self.platform(states=("pending", "failed"),
                                 failure_reason="workflow dipicu refs/tags/v1.1.0, bukan refs/tags/v1.2.0")
        result = self.run_script(platform)
        self.assertEqual(result.returncode, 1)
        self.assertIn("bukan refs/tags/v1.2.0", result.stdout)
        self.assertNotIn("/internal/v1/releases/rel_1/status", [request[1] for request in platform.requests])

    def test_galat_sementara_saat_bertanya_diulang(self):
        platform = self.platform(states=(502, 503, "pending", "signed"))
        result = self.run_script(platform)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rilis_yang_tidak_dikenali_berhenti(self):
        platform = self.platform(states=(404,))
        result = self.run_script(platform)
        self.assertEqual(result.returncode, 1)
        self.assertIn("menolak pertanyaan tentang rilis ini (404)", result.stdout)

    def test_menunggu_terlalu_lama_gagal(self):
        platform = self.platform(states=("pending",))
        result = self.run_script(platform, GONSU_RELEASE_SIGNING_TIMEOUT="0.2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("belum menandatangani rilis ini", result.stdout)
        self.assertNotIn("/internal/v1/releases/rel_1/status", [request[1] for request in platform.requests])

    def test_publikasi_ditolak(self):
        platform = self.platform(publish=(409, {"error": {
            "message": "Rilis tidak dapat diterbitkan: 2 kerentanan CRITICAL."}}))
        result = self.run_script(platform)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Publikasi ditolak GONSU (409)", result.stdout)
        self.assertIn("2 kerentanan CRITICAL", result.stdout)
        self.assertEqual(result.summary, "")

    def test_tanpa_izin_id_token(self):
        platform = self.platform()
        result = self.run_script(platform, ACTIONS_ID_TOKEN_REQUEST_URL=None)
        self.assertEqual(result.returncode, 1)
        self.assertIn("id-token: write", result.stdout)
        self.assertEqual(platform.requests, [])


if __name__ == "__main__":
    unittest.main()
