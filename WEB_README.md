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

## Deploy online

Repo da co san:

- `Dockerfile`
- `Procfile`
- `render.yaml`

Co the deploy len Render/Railway bang cach connect GitHub repo va chon web service. App tu doc bien moi truong `PORT` cua hosting.

Luu y: ban luu tru hien tai dung `web_data/photos.json` va `web_data/photos/`. Tren hosting mien phi, du lieu co the mat khi service restart/redeploy neu khong gan persistent disk.

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

App se luu:

- Anh strip doc 3 tam.
- 3 anh rieng trong bo chup.
- Metadata trong file JSON de de mo va kiem tra.

Du lieu nam trong:

```text
web_data/photos.json
web_data/photos/
```

Folder `web_data/` da duoc dua vao `.gitignore` de khong day anh nguoi dung len GitHub.
