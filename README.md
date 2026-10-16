# scad2fusion

Converter đọc source OpenSCAD và sinh Python chạy trong Autodesk Fusion. Bản đầu được kiểm tra với khay bông tắm, các SCAD độc lập và thay đổi tham số trong Fusion 2705.1.30.

## Cài và chuyển đổi

Cần Python 3.12+ và [uv](https://docs.astral.sh/uv/). Chạy từ thư mục repository:

```powershell
uv sync
uv run scad2fusion "tests/fixtures/tray.scad" --output "output\KhayBongTam"
```

Output:

```text
output/KhayBongTam/
  KhayBongTam.py
  KhayBongTam.manifest
  conversion-report.json
  README.md
```

Thư mục output phải mới và có tên hợp lệ cho Python, ví dụ `KhayBongTam`. Converter ghi gói hoàn chỉnh vào thư mục tạm rồi đổi tên; giữ nguyên mọi output đã có. Để tạo bản khác, chọn tên thư mục mới:

```powershell
uv run scad2fusion "tests/fixtures/tray.scad" -D hook_count=2 --output "output\KhayBongTamHaiMoc"
uv run scad2fusion "tests/fixtures/tray.scad" -D length=160 -D width=100 -D ear_rise=20 --output "output\KhayLon"
```

`-D` nhận số hoặc boolean JSON; kiểu phải khớp binding nguồn. SCAD assertion được kiểm tra trước khi tạo output. Source không được sửa. Báo cáo chứa source SHA-256, cấu hình, tham số, giới hạn và trạng thái kiểm chứng.

## Chạy trong Fusion

1. Mở **Utilities → Scripts and Add-Ins → Scripts → +**.
2. Chọn thư mục `output/KhayBongTam` chứa `.py` và `.manifest` cùng tên.
3. Chọn script rồi bấm **Run**. Script tạo document mới.
4. Mở **Modify → Change Parameters** để sửa các kích thước đã liên kết.

Gói output dùng Python chuẩn và `adsk` có sẵn trong Fusion; có thể copy cả thư mục sang đường dẫn khác. Fusion không cần source SCAD, package converter hoặc OpenSCAD để chạy gói này. `native-report.json` được ghi cạnh script, chứa build Fusion, feature health, bounds, thể tích và Pattern thực tế. Lỗi runtime giữ traceback cùng stage; document test dở dang được giữ để xem lỗi.

## Mức hỗ trợ

- Parser: biến số/boolean, biểu thức, `floor/min/max/abs` và một số hàm số học, vector/range, module đơn giản, `assert`, `if/else`, ternary, vòng lặp Cartesian. Bảo toàn biểu thức kích thước; điều kiện được chọn lúc sinh.
- Extension hộp bàn chải: function, `let`, indexing, nested comprehensions, vector arithmetic và cấu hình string/array; Revolve với một Fillet nhiều bộ bán kính cho các cung bo 90°; ren xoắn có quy luật dùng tối đa 5 Sweep theo các đoạn đổi bán kính, dùng chung một sketch đường dẫn. Mesh khác giữ BaseFeature từ mặt nguồn. Bán kính Fillet liên kết với tham số nguồn; ren cập nhật bằng sinh lại script. Report ghi representation, dependency, `update` và chuỗi lặp timeline; runtime từ chối chuỗi lặp quá 5 lần.
- Native: `cube`, cylinder thẳng; `square/circle` với `linear_extrude` thẳng; `offset(r)` trên square; Boolean 2D trong profile; `union/difference` solid, gồm composite cutter.
- Transform: translate; rotate/scale trong miền mặt phẳng extrusion song song XY/XZ/YZ. Hướng và frame thực tế được ánh xạ vào sketch; scale âm có ca khay kiểm chứng. Góc/scale của solid là lựa chọn lúc sinh.
- Lỗ lặp: vòng lặp range affine cắt bằng một extrusion được chuyển thành native rectangular Pattern. Số lượng và spacing có expression; biến thể 1 × 1 đã được kiểm tra.
- `$fn <= 12` giữ polygon đều chủ đích; circle/arc nhiều mặt dùng bề mặt native và ghi phép xấp xỉ. Chính sách này là một giới hạn tường minh, có đối chiếu mesh cho khay `$fn=64`.

Các cấu trúc ngoài miền được từ chối rõ; xem [compatibility](docs/compatibility.md). Đây là tập con của OpenSCAD, mở rộng theo từng input và regression mới.

## Thay đổi tham số

Ở khay một móc, dài/ngang/cao, thành/đáy, bo góc, kích thước tai, lỗ, lề và bước lỗ có công thức liên kết. Pattern lỗ đáy cập nhật số hàng/cột. Ở bản hai móc, khoảng cách và cao tâm móc cũng có liên kết.

`hook_count` quyết định cấu trúc lúc sinh: tạo lại gói với `-D hook_count=2` rồi chạy để tạo document khác. Vòng lặp chưa nhận dạng thành Pattern cũng cần sinh lại khi đổi số entity. `conversion-report.json` ghi `rebuild_parameters`, thông số transform và cơ chế của từng loop.

Giữ tham số trong miền hợp lệ của source khi chỉnh Fusion. Assertion kiểm tra lúc chuyển đổi; script không chạy nền để chặn tổ hợp sai trong Change Parameters. Tọa độ sketch giữ nhánh dấu lúc dựng; đổi qua zero, thay đổi symbolic zero hoặc thay topology/profile cần sinh lại. Tham số của nhánh không được chọn giữ metadata không đơn vị và không điều khiển hình học của gói hiện tại.

## Kiểm tra

```powershell
uv run python -m unittest discover -s tests -v
```

Test offline dùng fixture được lưu trong repo. Kiểm chứng Fusion, exports và đối chiếu OpenSCAD có hồ sơ riêng tại [testing](docs/testing.md).

Cài dependency audit riêng khi cần so mesh:

```powershell
uv sync --extra audit
uv run --extra audit python tools/compare_meshes.py reference.stl candidate.stl --report comparison.json
```

OpenSCAD chỉ cần cho bước đối chiếu, với executable theo môi trường. Converter hiện xử lý source trực tiếp, sử dụng lexer/parser và symbolic CSG nội bộ; không gọi compiler OpenSCAD hoặc framework CAD ngoài lúc chuyển đổi.

## Mở rộng

Với source dựng từ nhiều lát cắt, lập danh sách các đặc trưng khối, khoang, trục, lỗ và gân trước khi ánh xạ sang Fusion. Chọn extrusion, revolve hoặc loft liên tục cho vùng có quy luật; giữ biên dạng 2D gọn cho vùng đặc thù và đối chiếu sai lệch. Giữ sai lệch hình học trong ngưỡng kiểm chứng được công bố. Đối chiếu từng operation với miền hỗ trợ của converter ở trên; kiểm chứng native riêng cho gói được sinh.

`frontend_parser.py` phân tích cú pháp; `frontend.py` resolve scope/expressions và sinh IR. `units.py` suy đơn vị từ cách dùng hình học. `planar.py` giữ contour/CSG 2D; `native_runtime.py` dựng Sketch, Extrude, Combine và Pattern. `generator.py` đóng gói runtime cùng IR trong một `.py`; `cli.py` cung cấp lệnh.

Với hộp bàn chải điện:

```powershell
uv run scad2fusion "tests/fixtures/electric-toothbrush-case.scad" --output "output\HopBanChaiDien"
```

Mở thư mục gói trong Fusion Scripts rồi chạy `HopBanChaiDien.py`. Bố trí mặc định tạo thân và nắp đặt cạnh nhau theo source. `conversion-report.json` phân biệt kích thước có thể recompute và kích thước cần rebuild, gồm ren và datum trục quay cố định lúc Run. [Kiểm chứng hộp bàn chải](docs/toothbrush-validation.md) ghi cấu hình và bằng chứng cụ thể.

Một SCAD phức tạp hơn cần khảo sát cấu trúc còn thiếu, thêm fixture, mở rộng đúng operation/ngữ nghĩa rồi chạy lại offline/native regression. Roadmap gồm thư viện `include/use`, children, hull/minkowski, extrusion nâng cao, các plane tùy ý và Add-in.
