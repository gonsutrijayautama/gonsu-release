# GONSU Release — pipeline rilis produk

**Untuk tim yang membangun produk GONSU.**

Satu workflow GitHub Actions yang merilis sebuah produk ke platform GONSU One:
membangun image, mendorongnya ke registry GONSU, memindainya, mendaftarkannya,
menunggu GONSU menandatanganinya, lalu menerbitkannya. Repo produk tidak
menyalin langkah-langkah itu; ia memanggil workflow ini.

Project hasil `gonsu new` sudah membawa pemanggilnya.

## Memakainya

`.github/workflows/release.yml` di repo produk:

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: read

jobs:
  release:
    permissions:
      contents: read
      id-token: write
    uses: gonsutrijayautama/gonsu-release/.github/workflows/release.yml@v1
    with:
      product_code: garment
      variant_code: web
      image_path: products/garment-web
    secrets:
      registry_token: ${{ secrets.GONSU_REGISTRY_CI_TOKEN }}
```

Lalu, untuk merilis:

```sh
git tag v1.4.0 && git push origin v1.4.0
```

Tag `v1.4.0` menjadi versi `1.4.0`. Tag harus `vMAJOR.MINOR.PATCH`, boleh
dengan akhiran prarilis (`v1.4.0-rc.1`).

## Yang harus sudah ada

| Di mana | Apa |
|---|---|
| Console GONSU | Produk berkode `product_code` dengan variant `variant_code`. Salah ketik di salah satu sisi membuat registrasi ditolak. |
| Repo produk | Secret `GONSU_REGISTRY_CI_TOKEN`: token dorong registry, dari tim platform. Itu satu-satunya secret. |
| Repo produk | `Dockerfile` yang menerima `ARG VERSION`. Versi rilis diteruskan lewat `--build-arg VERSION`. |
| Akun GitHub | Repo produk berada di akun yang dipercaya platform. Repo di akun lain ditolak. |

Tidak perlu runner sendiri, dan tidak perlu akses ke jaringan GONSU: job ini
berjalan di runner GitHub.

## Masukan

| Masukan | Wajib | Bawaan | Isi |
|---|---|---|---|
| `product_code` | ya | | Kode produk di Console. |
| `variant_code` | ya | | Kode variant di Console. |
| `image_path` | ya | | Repository image di registry GONSU, misalnya `products/garment-web`. |
| `context` | | `.` | Konteks build docker. |
| `dockerfile` | | | Letak Dockerfile bila bukan `Dockerfile` di dalam konteks. |
| `api_url` | | `https://api.gonsu.cloud` | Alamat API GONSU. |
| `registry_host` | | `registry.gonsu.cloud` | Alamat registry GONSU. |

Dua yang terakhir hanya diisi untuk platform selain gonsu.cloud.

Rilis pertama sebuah produk **mengikat** dua hal ke produk/variant itu:
`image_path` dan repo GitHub yang merilisnya. Rilis berikutnya harus datang
dari repo yang sama dan mendarat di `image_path` yang sama. Mengubah salah
satunya dilakukan tim platform, bukan lewat workflow ini.

## Yang terjadi saat tag didorong

1. **Build** — image dibangun dari commit yang ditandai tag.
2. **Push** — ke registry GONSU, sebagai `<image_path>:<versi>`.
3. **Scan** — trivy memindai image; laporannya disimpan utuh.
4. **Register** — image, laporan pemindaian, dan bukti asal job dikirim ke
   GONSU. Rilisnya berstatus `staged`: terlihat staf GONSU, belum terlihat
   pelanggan.
5. **Tanda tangan** — GONSU memeriksa bukti itu sendiri, lalu menandatangani
   image dan laporan pemindaiannya.
6. **Publish** — rilis terbit dan dapat dipasang pelanggan.

Workflow ini tidak memegang kunci penandatangan. Yang dibawanya adalah bukti
dari GitHub tentang job yang sedang berjalan: repo mana, tag apa, commit mana.
GONSU menandatangani hanya bila bukti itu cocok dengan rilis yang didaftarkan:

- repo-nya yang terikat ke produk;
- pemicunya tag, bukan cabang atau pull request;
- tagnya sama dengan versi rilis;
- commit-nya sama dengan commit asal rilis;
- image dan laporan pemindaiannya persis yang dikirim;
- job-nya dijalankan workflow ini pada cabang `v1` — bukan salinannya, dan
  bukan ref lain.

Karena itu workflow ini hanya berguna bila dipicu tag. Dipanggil dari cabang
atau pull request, ia berhenti di langkah pertama.

## Bila gagal

Sebabnya tercetak di log job, dalam kalimat. Yang paling sering:

| Pesan | Artinya | Yang dilakukan |
|---|---|---|
| `Tag … bukan vMAJOR.MINOR.PATCH` | Bentuk tag salah. | Hapus tagnya, dorong tag yang benar. |
| `Registrasi rilis ditolak GONSU (400)` | Kode produk/variant tidak dikenal, atau `image_path` bukan yang terikat ke produk. Field yang salah disebut di pesannya. | Samakan dengan Console. |
| `Registrasi rilis ditolak GONSU (403)` | Repo ini bukan milik akun GitHub yang dipercaya platform, atau bukan repo yang terikat ke produknya. Alasannya ikut tercetak. | Rilis dari repo produknya; selebihnya hubungi tim platform. |
| `Registrasi rilis ditolak GONSU (403)` … `Job ini tidak dijalankan pipeline rilis milik platform` | Pemanggil menunjuk ref selain `@v1`, atau langkah workflow ini disalin ke repo produk. GONSU hanya menandatangani hasil workflow ini pada `v1`. | Panggil `gonsutrijayautama/gonsu-release/.github/workflows/release.yml@v1`, tanpa menyalinnya. |
| `Registrasi rilis ditolak GONSU (409)` | Versi itu sudah terdaftar dan sudah ditandatangani, atau image yang sama sudah menjadi versi lain. | Rilis dengan nomor versi baru. |
| `GONSU menolak menandatangani rilis ini` | Bukti tidak cocok dengan rilis; alasannya ikut tercetak. | Perbaiki sebabnya, lalu jalankan ulang job. |
| `GONSU belum menandatangani rilis ini sesudah … detik` | Platform sedang tidak mengerjakan tanda tangan. | Hubungi tim platform; rilisnya tetap `staged`. |
| `Publikasi ditolak GONSU` | Ada kerentanan yang menghalangi menurut kebijakan platform. | Perbarui dependency atau image dasar, lalu rilis versi baru. |

Rilis yang gagal tertinggal di `staged` dan tidak pernah terlihat pelanggan.
Job yang gagal sebelum ditandatangani boleh dijalankan ulang; sesudah
ditandatangani, versi itu tidak dapat didaftarkan lagi.

## Versi workflow ini

Panggil `@v1`. `v1` adalah cabang: perbaikan masuk ke `main`, lalu `v1`
dimajukan ke sana sesudah CI hijau. Perbaikan yang tidak mengubah cara
memanggilnya langsung dipakai setiap produk pada rilis berikutnya, tanpa
perubahan di repo produk. Perubahan yang menuntut penyesuaian di repo produk
terbit sebagai `v2`.

Jangan memanggil `@main` atau ref lain: GONSU menolak rilis yang tidak
dijalankan dari `v1`.

## Mengembangkan repo ini

```sh
python3 -m unittest discover -s tests -v
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:1.7.12
```

Skrip registrasi hidup di dalam workflow, bukan di berkas tersendiri: workflow
yang dipanggil dari repo lain hanya membawa dirinya. `tests/` mengambilnya dari
sana dan menjalankannya terhadap GONSU tiruan.

`Probe` (Actions → Probe → Run workflow) menguji sisi sebaliknya terhadap
platform sungguhan: job dari workflow selain `release.yml` harus ditolak. Ia
lulus bila platform menolak. Jalankan sesudah platform diperbarui atau daftar
workflow yang dipercayanya diubah.

## Lisensi

Bukan sumber terbuka; lihat [LICENSE](LICENSE).
