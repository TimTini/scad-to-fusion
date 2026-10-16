# Dustpan — converter native, 2026-10-16

## Bản giảm cạnh, giữ hình

Bản mới tại `output/dustpan-clean-final/Dustpan` đã chạy trực tiếp trong Fusion 2705.1.30: **97 mặt / 267 cạnh**, so với 104 mặt / 286 cạnh của bản trước (giảm 19 cạnh, 6,64%). Một solid khỏe, mọi sketch đủ ràng buộc; timeline vẫn 132 mục, block lặp tối đa 5 lần, 2 Fillet / 5 Loft / 2 Sweep / 0 BaseFeature. 176 test offline đạt. Số liệu và hash của đúng bản bàn giao nằm trong [dustpan-edge-validation.json](validation/dustpan-edge-validation.json).

Sửa nguồn recovery để hai cung dùng chung endpoint và khôi phục tiếp tuyến line/arc ở đường Sweep khi đoạn nối bị lấy mẫu thiếu điểm tiếp xúc. Chỉ gộp khi support line tiếp xúc đúng đường tròn, hướng đi cùng chiều, endpoint lệch pháp tuyến tối đa 0,02 mm và phần mở rộng cung tối đa 15°. Giữ các chỗ nối không đủ điều kiện; không xóa mặt theo diện tích. Candidate 91 mặt / 251 cạnh trước khi siết điều kiện không phải bản bàn giao.

Các số liệu 104 mặt / 286 cạnh và 172 test ở phần dưới ghi nhận checkpoint trước khi giảm cạnh; source và các output cũ được giữ lại. Đây là cải thiện nhỏ về topology, chưa loại hết đường chia mặt trên Fusion.

So với bản bàn giao trước, mesh mới có sai lệch bề mặt lấy mẫu **0,007329 mm**, sai lệch thể tích **0,00000322%**; ba mặt cắt giữ nguyên số vòng. So với SCAD, sai lệch lấy mẫu **0,117960 mm**, thể tích **0,010017%**, symmetric difference **0,029425%**; một mesh kín, bounds khớp. Đạt contract dustpan 0,15 mm / 0,25%; comparator chung 0,05 mm vẫn báo `failed` và được giữ nguyên trong hồ sơ. Phép đo lấy mẫu không phải chứng minh Hausdorff chính xác.

Converter đọc trực tiếp source và sinh package standalone; không gọi builder Dustpan dựng riêng. Fixture `tests/fixtures/dustpan.scad` có SHA256 `9f8a284a37d630a114eb1b5773fc276a5a30d8fef1dacd14db03247d8cb54db2`, khớp source đầu vào được giữ nguyên. Bàn giao cả thư mục `output/dustpan-final/Dustpan`, không ZIP.

## Kết quả native và kiểm chứng

Bản mặc định chạy trong Fusion 2705.1.30: một solid, **104 mặt / 286 cạnh**, **132 mục timeline**; block Plane/Sketch lặp tối đa **5 lần**. Có 2 Fillet, 5 Loft, 2 Sweep, 0 BaseFeature và 2 Revolve cho góc sau. Mọi sketch đủ ràng buộc, feature khỏe. Hai cấu hình rebuild tắt bốn gia cường và tăng width/depth 220, thickness 4, total_height 270 cũng khỏe; bản tắt gia cường chỉ có 17 mục timeline. 15 ca native hồi quy cũ và 172 test offline đạt. Xem [bằng chứng](validation/dustpan-converter-validation.json).

Contract đã có của project nguồn: bounds 0,05 mm, thể tích 0,25%, bề mặt lấy mẫu 0,15 mm; giữ thêm symmetric difference 0,5% của converter. Ba phép so mesh đạt contract này:

- Mặc định: surface 0,117960 mm; volume 0,010021%.
- Tăng kích thước: surface 0,130049 mm; volume 0,007952%.
- Tắt gia cường: surface 0,008617 mm; volume 0,003363%.

Mỗi ca có một mesh kín; số vòng ở ba mặt cắt khớp. Phép đo dùng toàn bộ đỉnh và 10.000 điểm lấy mẫu mỗi mesh, không phải chứng minh Hausdorff chính xác. STL của thư mục bàn giao cuối khớp toàn bộ byte với candidate mặc định đã so; SHA256 source, reference, candidate và script được lưu riêng.

**Comparator chung vẫn dùng ngưỡng surface 0,05 mm:** mặc định và scaled giữ trạng thái `failed` theo ngưỡng chung; original giữ `passed`. Hồ sơ công bố cả raw status và acceptance theo contract dustpan 0,15 mm, không sửa raw status. Giới hạn này cần được đọc cùng các số liệu trước khi dùng kết quả.

## Cách dựng và giới hạn cập nhật

Frontend bổ sung comprehension `each`/`if`, cache theo dependency bắc cầu, implicit union của module nhiều khối, `multmatrix`, `hull`, `offset(delta)`. Polygon nhiều mẫu được khôi phục line/arc/circle theo ngưỡng sai số. Nhận dạng dựa trên hình học, không theo tên file/module/tham số.

- Sector góc sau dùng Revolve, giữ các điểm đổi luật bán kính. Loft toàn vùng đã thử nhưng bị loại vì làm sai hình dù feature khỏe.
- Cove offset tròn dùng Fillet R−0,01 mm để tránh điểm suy biến của cung lõm tại bán kính đầy đủ. Biên xấp xỉ được khai báo và so mesh.
- Vành có tiết diện dịch chuyển giữ nguyên dùng parallel Sweep; prefix chia tại điểm đổi luật bằng Loft hai tiết diện.
- Đáy quintic dùng tối đa 5 profile và extrusion cho phần đuôi có tiết diện cố định.

Các vùng numeric được đánh dấu `rebuild`: đổi tham số rồi sinh thư mục mới từ SCAD và Run. Tên trùng đơn vị Fusion được ánh xạ tường minh, ví dụ `hr` → `scad_hr`. Fusion parameter engine thiếu `atan2`: giá trị derived đóng băng, giữ `source_expression` và nhãn rebuild. Các profile layered có normal nghiêng ngoài miền hiện tại bị từ chối ở preflight; sector/cove có kiểm tra scale riêng. Mesh ngoài miền nhận dạng vẫn có thể giữ faceted representation.

Standalone import bằng Python `-I -S` và build wheel đã kiểm tra. In/lắp, thử tải, slicer và kiểm tra self-intersection độc lập giữ `not_run`. Source, output và exports cũ được giữ nguyên.

## Tái lập

```powershell
uv run scad2fusion tests/fixtures/dustpan.scad --output output/DustpanNew
uv run scad2fusion tests/fixtures/dustpan.scad -D reinforce_floor=false -D reinforce_handle=false -D reinforce_walls=false -D reinforce_rim=false --output output/DustpanOriginalNew
uv run scad2fusion tests/fixtures/dustpan.scad -D width=220 -D depth=220 -D thickness=4 -D total_height=270 --output output/DustpanScaledNew
uv run --extra audit python -m unittest discover -s tests
```

Chạy package qua Fusion Scripts hoặc harness `tools/run_fusion_validation.py` với `bounds_tolerance_mm: 0.05`. Xuất reference bằng OpenSCAD Manifold; candidate bằng Fusion high refinement với surfaceDeviation 0,002 mm. So mesh qua `tools/compare_meshes.py --section Z=3.5 --section Y=70 --section X=0`; ca scaled dùng Z4,5/Y75/X0. Giữ kết quả comparator chung và đánh giá contract dustpan riêng. Các run local nằm trong `work/dustpan-implementation-001`, không nằm trong public Git.

## Intake trước triển khai

Tại commit `a1332ac`, converter dừng ở dòng 53 (`each concat`). Sáu probe độc lập xác nhận thiếu `each`, comprehension filter, `multmatrix`, `hull`, solid intersection và `offset(delta)`. OpenSCAD render nguồn thành công: một component kín, bounds 206 × 215 × 250 mm, 20.252 facets. Đây là kết quả chẩn đoán ban đầu; các checkpoint triển khai và thử nghiệm bị loại được giữ trong [development-progress.md](development-progress.md).
