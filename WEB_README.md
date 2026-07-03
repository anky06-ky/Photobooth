# Puzzle Cam Web

Ban web chay local tren laptop.

## Chay app

```powershell
python web_server.py
```

Mo trinh duyet:

```text
http://127.0.0.1:8000
```

Hoac bam `run_web.bat`.

## Deploy online tren Netlify

Repo da co san:

- `netlify.toml`
- `netlify/functions/photos.js`
- `package.json`

Netlify se publish folder `web/`, route `/api/photos` vao Netlify Function, va luu anh online bang Netlify Blobs.

Neu Netlify dang hien 404, vao project va trigger `Deploys -> Trigger deploy -> Clear cache and deploy site` de Netlify doc lai `netlify.toml`.

## Cach dung

1. Bam `Bat camera`.
2. Bam `Chup tam 1/3`.
3. Keo tha cac manh puzzle de ghep dung anh.
4. Bam `Nhan tam nay` de luu tam tam hien tai vao bo 3 tam. Co the bam `Tu ghep xong` neu muon app xep puzzle nhanh.
5. Lap lai cho tam 2 va tam 3.
6. Khi du 3 tam, bam `Luu strip vao thu vien`.

## Dieu khien bang tay

1. Bam `Bat dieu khien tay`.
2. Dua tay vao camera.
3. Kep ngon cai + ngon tro de nam va keo manh puzzle.
4. Tha kep de dat manh vao o gan nhat.
5. Gio dau `Like` khoang nua giay de nhan tam hien tai.

Nut `Nhan tam nay` van nam o cot phai de dung du phong neu tracking tay chua on.
Tinh nang tay can internet de tai thu vien MediaPipe web lan dau.

Khi chay local bang `python web_server.py`, app se luu:

- Anh strip doc 3 tam.
- 3 anh rieng trong bo chup.
- Metadata trong file JSON de de mo va kiem tra.

Du lieu nam trong:

```text
web_data/photos.json
web_data/photos/
```

Folder `web_data/` da duoc dua vao `.gitignore` de khong day anh nguoi dung len GitHub.
