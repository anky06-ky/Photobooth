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

## Cach dung

1. Bam `Bat camera`.
2. Bam `Chup tam 1/3`.
3. Keo tha cac manh puzzle de ghep dung anh.
4. Bam `Nhan tam nay`.
5. Lap lai cho tam 2 va tam 3.
6. Khi du 3 tam, bam `Luu strip vao database`.

App se luu:

- Anh strip doc 3 tam.
- 3 anh rieng trong bo chup.
- Metadata trong SQLite database.

Du lieu nam trong:

```text
web_data/photobooth.sqlite3
web_data/photos/
```

Folder `web_data/` da duoc dua vao `.gitignore` de khong day anh nguoi dung len GitHub.
