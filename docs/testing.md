# Kiểm chứng MVP — 15/16-10-2026

Phân biệt source/offline, Fusion native, export và mesh comparison. Bản này kiểm chứng trên Windows, Python 3.12.14, OpenSCAD 2026.09.29/Manifold và Fusion 2705.1.30. Phạm vi chưa gồm macOS, máy thứ hai hoặc bản in vật lý.

Phần dưới giữ hồ sơ MVP57offline/13native/5mesh. Extension hiện tại có93offline tests và bộ regression15native, thêm Revolve/polyhedron cutters và quarter-revolve có phase. Hồ sơ hộp bàn chải cùng các gate mới ở [toothbrush validation](toothbrush-validation.md); bằng chứng regression mới ở [toothbrush-regression.json](validation/toothbrush-regression.json).

Input gốc và fixture `tests/fixtures/tray.scad` cùng SHA-256:

`68dcee6010b2ac1447bc45a723c83127197f769bfd0c90ddc4393b1d1d923f9e`

## Offline

```powershell
uv sync
uv run python -m unittest discover -s tests -v
uv build
```

57 test đã đạt. Bao gồm lexer/parser/scope, biểu thức đúng thứ tự, overrides, assertions, lỗi nguồn và guard, symbolic contour, đơn vị, loop Pattern affine, package độc lập, overwrite và lỗi ghi đĩa. Source distribution đưa cả fixture SCAD và tools/docs qua `MANIFEST.in`. Wheel đã được cài không dependency trong virtualenv mới và chạy với `-I` từ ngoài checkout để chuyển input gốc. Python output đã import bằng `-I -S`, xác nhận không phụ thuộc package converter hoặc site-packages.

## Native

Gói được kiểm tra là Python sinh từ converter, độc lập với script dựng riêng có sẵn của khay. Mỗi ca chạy trong document mới; harness phục hồi expressions rồi đóng riêng document nó tạo, giữ document đã mở trước khi test.

13 ca bao gồm:

- Khay baseline: một solid 100 × 70 × 47 mm; Pattern 7 × 5; tâm móc X50/Z38.5 mm.
- Khay lớn: 160 × 100 × 50 mm; Pattern 12 × 7; tâm móc X80/Z40 mm.
- Khay nhỏ: 52 × 21 × 47 mm; Pattern 1 × 1; tâm móc X26/Z38.5 mm.
- Hai móc baseline: 100 × 70 × 30 mm; tâm X20/X80 và Z20 mm.
- Hai móc biến thể: dài150 mm, khoảng tâm80 mm, cao tâm22 mm; tâm X35/X115.
- Composite difference: hai solid, tổng194 mm³, giữ đúng phần đảo còn lại của nested cutter.
- Union có bridge nối hai nhóm: một solid6 × 2 × 2 mm, thể tích24 mm³.
- Cylinder `$fn=6`: hexagonal prism thật, không đổi thành trụ tròn.
- Đổi tên module, `length→span_x`, `width→span_y`: baseline và resize vẫn đúng.
- SCAD plate độc lập: baseline20 × 10 × 3 mm/600 mm³ và resize25 × 10 × 4 mm/1000 mm³.
- Gói copy sang thư mục có dấu và khoảng trắng: chạy độc lập trong cùng máy.

Mỗi ca kiểm tra computeAll, health của feature, sketch đủ ràng buộc, body/bounds, Pattern count và các tâm circle/kích thước có expected. Tạo STEP baseline và STL từng biến thể. Bằng chứng chi tiết và script SHA-256: [native-validation](validation/native-validation.json), [artifact manifest](validation/artifact-manifest.json).

Tái lập từ checkout mới với Fusion đang mở và local MCP được bật tại Preferences/API:

```powershell
uv run python tools/prepare_native_suite.py
uv run python tools/run_fusion_validation.py work/evidence/native-suite/config.json
```

Lệnh đầu hiện tạo15case:13case MVP và2fixture extension. Config được ghi trong thư mục mới. Chạy lại suite bằng thư mục khác, ví dụ `uv run python tools/prepare_native_suite.py work/evidence/suite-next`. Runner mặc định port27182; đọc port thật từ Fusion khi môi trường khác. Runner dùng JSON MCP một connection và xác nhận response; script dispatch dùng Python Unicode escapes để giữ đường dẫn có dấu qua transport.

Lần native suite đầu có12 ca đạt và ca portable lỗi encoding ở dispatch. Ca portable chạy riêng đạt sau khi sửa transport; toàn bộ suite được chạy lại để chốt gate. Giữ log thất bại trong `work/evidence/final-native/`, không dùng nó làm bằng chứng thành công.

## So sánh geometry

Công cụ audit là dependency tùy chọn, tách khỏi converter và runtime Fusion:

```powershell
uv sync --extra audit
uv run --extra audit python tools/compare_meshes.py reference.stl candidate.stl --report comparison.json
```

Reference được render mới bằng OpenSCAD Manifold từ cùng fixture/overrides. Mesh Fusion xuất với surface deviation0.002 mm. So bounds, watertight/connectivity, thể tích, symmetric difference bằng Manifold, mặt cắt đáy tạiZ1.5 mm và thành sau tạiYmax−1.5 mm. Đo khoảng cách bề mặt hai chiều trên toàn bộ vertex và10.000 điểm surface deterministic mỗi mesh; đây là sampled deviation, chưa phải chứng minh Hausdorff chính xác.

Ngưỡng: bounds/sampled surface ≤0.05 mm; chênh thể tích và symmetric difference tương đối ≤0.5%; một component và số vòng mặt cắt trùng nhau cho từng khay. Baseline đã đo bounds0 mm, sampled surface0.00963332 mm, relative volume0.002715%, symmetric difference0.039983%; mặt cắt đáy36 vòng và thành sau2 vòng khớp reference.

Cả năm biến thể khay đều đạt: bounds error0 mm; sampled surface tối đa0.00963946 mm; relative volume tối đa0.040018%; symmetric difference tối đa0.094273%. Các mặt cắt có số vòng khớp reference: đáy lần lượt36/85/2/36/56, thành sau2/2/2/3/3. [Geometry reports](validation/geometry-comparison.json) giữ actual cho từng ca. Đây là số đo trên tessellation và sampling đã mô tả, không đại diện độ chính xác bản in.

## Giới hạn

Test đạt theo miền và phiên bản trên. Tọa độ qua zero, thay cấu trúc nhánh, operation ngoài backend, miền tham số sai và topology profile khác vẫn cần rebuild hoặc extension như [compatibility](compatibility.md). Conversion report phản ánh check lúc sinh; `native-report.json` và validation suite mới là bằng chứng chạy Fusion. Slicer, in/fit/tải/thoát nước thực tế chưa được kiểm chứng.
