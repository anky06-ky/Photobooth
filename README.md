# Puzzle Cam Web

Web photobooth chup 3 tam, ghep puzzle, luu strip doc va quan ly anh trong thu vien.

## Chay local

```powershell
python web_server.py
```

Mo:

```text
http://127.0.0.1:8000
```

Hoac bam `run_web.bat`.

## Deploy Netlify

Repo da co san cau hinh:

- `netlify.toml`
- `netlify/functions/photos.js`
- `package.json`

Netlify publish folder `web/`, route `/api/photos` vao Netlify Function, va luu anh online bang Netlify Blobs.

Neu site bi 404, vao Netlify:

```text
Deploys -> Trigger deploy -> Clear cache and deploy site
```

## Dung tren Android va iOS

App da co PWA:

- `web/manifest.webmanifest`
- `web/sw.js`
- meta tag rieng cho iOS
- layout responsive cho man hinh dien thoai

Android:

1. Mo link Netlify bang Chrome.
2. Bam menu 3 cham.
3. Chon `Add to Home screen` hoac `Install app`.

iOS:

1. Mo link Netlify bang Safari.
2. Bam nut Share.
3. Chon `Add to Home Screen`.

Camera tren dien thoai can HTTPS. Link Netlify co HTTPS san, con local `127.0.0.1` chi dung tren laptop.

## Cau truc

```text
web/                    giao dien camera/puzzle
netlify/functions/      API luu, doc, xoa anh online
scripts/                script build copy model tay
models/                 MediaPipe hand model
web_server.py           server local bang Python
web_data/               du lieu local, khong push len GitHub
```

## Cach dung

1. Bat camera.
2. Chup tam 1/3.
3. Keo puzzle bang chuot hoac bat dieu khien tay.
4. Bam `Luu tam 1/3` hoac gio Like de nhan tam.
5. Lap lai den 3/3.
6. Bam `Luu strip vao thu vien`.
