# x3book

Công cụ dòng lệnh chỉnh EPUB cho máy đọc sách **Xteink X3** chạy firmware **CrossVi**.

[English section below](#english)

## Làm gì

- `tune`: tối ưu EPUB (ảnh, entity, bảng layout, mục lục) theo một file plan JSON.
- `check`: báo những gì CrossVi sẽ lỗi, và nhãn footer của từng file trong spine.
- `pdf`: PDF có text -> EPUB reflow.
- `merge`: ghép nhiều nguồn (PDF + Markdown) thành một EPUB theo plan.
- `flashbook`: file Markdown tóm tắt sách -> EPUB (`build`), kiểm độ dài (`stats`), EPUB -> text (`source`).
  `build --target std` ra EPUB 3 cho điện thoại / PC / Kindle (mặc định `x3`: EPUB 2 cho CrossVi).
- `convert`: azw3 / mobi / docx / fb2 -> EPUB bằng Calibre, rồi `tune`. **Không hỗ trợ file DRM.**

## Vì sao X3 / CrossVi cần công cụ này

- Footer của CrossVi chỉ hiện **một mục lục cho mỗi file** trong spine: mục đầu tiên trỏ vào file đó.
  Sách có nhiều chương trong một file sẽ hiện sai tên chương. Plan `split` tách mỗi chương thành một file riêng.
- Ảnh JPEG **progressive** bị giải mã ở độ phân giải 1/8 trên máy. `tune` đổi sang **baseline**, thang xám, cạnh dài tối đa 792 px.
- CrossVi chỉ giải mã jpg và png.
- Parser expat dừng chương ở entity HTML không định nghĩa (vd `&emsp;`). `tune` đổi sang entity số.
- Bảng layout chỉ chứa ảnh bị in thành nhãn "Tab Row N, Cell M". `tune` bỏ bảng đó.

## Cài đặt

```
pip install git+https://github.com/HoangTran-17/x3book
```

Cần Python 3.10 trở lên. Phụ thuộc: `lxml`, `Pillow`, `pymupdf`.
Tuỳ chọn: `pip install mobi` để `tune` đọc thẳng file `.azw3`. `convert` cần [Calibre](https://calibre-ebook.com/download) (`ebook-convert` trong PATH).

## Ví dụ

```
x3book tune  in.epub  "in [X3].epub"  plan.json     # plan.json tuỳ chọn
x3book check "in [X3].epub"
x3book tune  book.pdf book.epub  pdf-plan.json      # PDF cần khối "pdf" trong plan
x3book merge merge-plan.json --dump dump/
x3book flashbook build book.md out/
x3book flashbook build book.md out/ --target std    # EPUB 3 cho điện thoại / PC / Kindle
x3book convert book.azw3                            # -> "book [X3].epub"
```

File mẫu nằm trong `examples/` (nhãn giả, không chứa nội dung sách).

### Plan cho `tune`

```json
{
  "relabel": {"CHAPTER ONE": "Chapter 1 - Title"},
  "drop": ["Copyright"],
  "split": [{"file": "text/a.xhtml", "before_id": "ch2"},
            {"file": "text/a.xhtml", "before_text": "CHAPTER THREE"}],
  "chapters_from": {"class": "chapter-heading", "heading_tag": "h2"},
  "pdf": {"...": "chỉ dùng khi nguồn là PDF"}
}
```

- `relabel` / `drop`: đổi tên / bỏ mục trong `toc.ncx`. Nhãn không tìm thấy thì lệnh dừng với lỗi.
- `split`: cắt một file tại `before_id` hoặc `before_text`.
- `chapters_from`: dựng mục lục từ các đoạn tiêu đề có class cho trước.

### Tuỳ chọn bổ sung (mặc định tắt)

Học từ `epub-to-xtc-converter` (xem [NOTICE](NOTICE)):

- `--strip-fonts`: xoá font nhúng.
- `--clean-css`: xoá `float` / `position` / `flex` / `grid` / `transform` và `@font-face`.
- `--convert-images`: GIF / WebP / BMP / TIFF -> JPEG baseline.
- `--strip-data-uris`: thay `src="data:..."` bằng `#`.
- `--epaper`: bật cả bốn.

## Chạy test

```
pip install -e ".[dev]"
pytest -q
```

Test dùng EPUB tổng hợp trong thư mục tạm, không cần sách thật.

## Giấy phép

MIT. Xem [LICENSE](LICENSE) và [NOTICE](NOTICE).

---

<a id="english"></a>

## English

`x3book` tunes EPUB files for the Xteink X3 e-reader running the CrossVi firmware.

Why:

- CrossVi shows one footer label per spine file: the first TOC entry that points at that file. Put each chapter in its own file.
- Progressive JPEG decodes at 1/8 size on the device. Use baseline JPEG, grayscale, max 792 px.
- Undefined HTML entities (`&emsp;`) stop the expat parser. They become numeric entities.

Commands: `tune`, `check`, `pdf`, `merge`, `flashbook build|stats|source`, `convert`.
`flashbook build --target std` writes an EPUB 3 for phone / PC / Kindle apps (default `x3`: EPUB 2 for CrossVi).
DRM-protected files are not supported.

Install:

```
pip install git+https://github.com/HoangTran-17/x3book
```

Use:

```
x3book tune in.epub out.epub plan.json
x3book check out.epub
x3book convert book.azw3        # needs Calibre
```

Optional clean-ups, off by default (`--strip-fonts`, `--clean-css`, `--convert-images`, `--strip-data-uris`, `--epaper`) are re-implemented from
[bigbag/epub-to-xtc-converter](https://github.com/bigbag/epub-to-xtc-converter) (MIT). See [NOTICE](NOTICE).

License: MIT.
