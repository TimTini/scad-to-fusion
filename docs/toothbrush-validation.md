# Hộp bàn chải điện — kiểm chứng converter

## Bản native đơn giản hóa

Nhánh `work/analytic-geometry` đã tích hợp Revolve với **10 Fillet native** nối biểu thức bán kính và **2 Loft ren tiết diện tròn**. Cấu hình mặc định có hai solid: thân **33 mặt/51 cạnh**, nắp **10 mặt/9 cạnh**; không dùng BaseFeature. Các cung 90° được nhận dạng từ công thức tâm/bán kính/cặp sin-cos, tạo profile nhọn rồi Fillet. Ren giữ pitch, phase, đoạn thu nhỏ hai đầu; thay đổi ren vẫn cần sinh lại script.

Fusion 2705.1.30 đã chạy 5 cấu hình: layout baseline, đổi chiều cao, đổi sáu bán kính bo qua Change Parameters, thân tùy chỉnh và assembled. Mọi feature khỏe, sketch đủ ràng buộc, bounds và số solid đúng. Cấu hình thân tùy chỉnh cố ý dùng tiết diện ren 12 cạnh nên giữ đường polyhedron/BaseFeature; việc giữ polygon ít cạnh là giới hạn có chủ đích.

Đối chiếu cả 5 cấu hình với source OpenSCAD đều đạt ngưỡng: sai lệch bề mặt lấy mẫu lớn nhất **0,034748 mm**, thể tích **0,013649%**, symmetric difference **0,056590%**. Các mặt cắt Z1,5 / Z75 / Z205 / Y0,123 có số vòng trùng nhau giữa reference và candidate; mesh kín và số component khớp. Đây là phép đo lấy mẫu, không phải chứng minh Hausdorff chính xác hay kiểm chứng lắp/vặn vật lý. Bộ 15 ca native hồi quy cũ cũng đạt với mã hiện tại.

Bằng chứng: [native, mesh, regression và artifact hashes](validation/native-smooth-validation.json). Script bàn giao có SHA256 `7a49493be6bfd6c4d27aafde908b9484db8c00a0edda637a7b19e14212ffdb3a`. `output/HopBanChaiDien` và ZIP `dist/HopBanChaiDien-smooth-fusion.zip` chứa đúng script đã chạy; output và artifact lớn giữ local, không nằm trong Git. Dựng mới bằng CLI từ fixture để tái lập.

Timeline mặc định có 253 mục do mỗi section Loft cần sketch và construction plane; hình học solid đã giảm mặt/cạnh, nhưng số mục timeline chưa được tối ưu. Bán kính bo cập nhật trực tiếp được kiểm tra trong miền thay đổi đã ghi ở bằng chứng; count, ren và transform được đánh dấu rebuild theo report.

## Baseline trước đơn giản hóa — tag v0.1.0

Nguồn tham chiếu: `tests/fixtures/electric-toothbrush-case.scad`, SHA256 `e32750b76ff4c8620786dfb8463b2d917a5bd6aad8b2ca1f9b32c61d5207fca4`. Fixture `tests/fixtures/electric-toothbrush-case.scad` là bản sao nguyên trạng. Source project được giữ nguyên; script Fusion viết tay trong project đó không phải output converter và không thay thế geometry SCAD làm căn cứ.

Converter đọc trực tiếp các hàm profile và `round_thread()`. Hai thân dùng native Revolve từ polygon radial/Z, hai ren dùng solid BRep BaseFeature từ 25.968 vertex và 51.844 mặt của source. Giữ phase, pitch, mặt cắt radial/Z và fade45° với bán kính tối thiểu `thread_embed/4`. Bề mặt xoay native thay các mặt góc OpenSCAD; đây là sai khác analytic có đo kiểm.

`conversion-report.json` ghi chính sách cập nhật từng tham số. Chiều cao thân/nắp điều khiển sketch profile; ren polyhedron, số lỗ và các datum cố định lúc Run cần sinh lại. Dependency rebuild mở rộng tới cả input phía trên của derived parameter. Thay đổi tham số cần giữ miền hợp lệ theo assertions SCAD. `section`/`bottom_detail` cần backend solid intersection, hiện được chẩn đoán ngoài miền hỗ trợ.

## Tái hiện

Cài audit extra và chuẩn bị suite vào thư mục mới:

```powershell
uv sync --extra audit
uv run --extra audit python tools/prepare_toothbrush_suite.py `
  "tests/fixtures/electric-toothbrush-case.scad" `
  "work\evidence\toothbrush-suite-new" `
  --openscad "tools/openscad/openscad.com"
uv run python tools/run_fusion_validation.py "work\evidence\toothbrush-suite-new\config.json"
```

Fusion phải đang chạy cùng MCP endpoint của máy. Harness tạo document test riêng, phục hồi expressions sau mỗi variant, đóng các document do mình tạo và khôi phục document active trước test. Các gói Python chạy độc lập với converter/OpenSCAD trong Fusion.

Suite gồm layout đầy đủ, đổi `body_height=219.6`/`cap_height=90.2` bằng Change Parameters; body bảy lỗ,1.5vòng ren với sampling64×12; assembled sampling64×12 giữ phase/quan hệ lắp source. Những ca sampling thấp là cấu hình SCAD riêng, có render tham chiếu riêng.

```powershell
uv run --extra audit python tools/compare_meshes.py reference.stl native.stl `
  --section Z=1.5 --section Z=75 --section Z=205 --section Y=0.123 --report comparison.json
```

Auditor so số component theo reference, mesh kín, bounds, thể tích, Boolean symmetric difference, mặt cắt và toàn bộ vertices cộng10.000 mẫu bề mặt cố định mỗi chiều. Truy vấn bề mặt chia batch256 để giới hạn RAM. Sai lệch bề mặt là phép lấy mẫu; chưa phải chứng minh Hausdorff chính xác hay kiểm chứng vật lý.

## Trạng thái

Offline:93 tests passed, Python3.12.14. Wheel cài trong môi trường Python3.14.7 riêng, gọi bằng `-I` ngoài checkout trên source gốc; output script import được bằng `-I -S` và byte-identical với script chạy native. Fixture có Git attribute giữ nguyên byte/hash trên các hệ điều hành.

Suite012 trong Fusion2705.1.30 đạt cả4case: layout baseline, height_resize, body_custom, assembled. Layout có2solids, bounds[-25.7,-25.7,0]..[89.1,25.7,213.6]mm,3sketches đủ ràng buộc và timeline14. Bản trung gian chưa gộp lỗ có timeline67/21sketches; volume native baseline giữ nguyên. Body custom có1solid/timeline8; assembled có1solid/timeline15, boundsZ0..285.2 theo source union. Height resize đạtZ219.6 và cap90.2mm bằng native parameter expressions.

Regression-v4 đạt15/15case, gồm13case MVP trước và2fixture mới: cutter Revolve/polyhedron cùng quarter-revolve90° đã xoay profile90°. Ca quarter-revolve kiểm tra quadrantII, bounds[-2,0,0]..[0,2,3]mm; source-frame reflection được bù qua dấu sweep, Move chỉ chứa proper rotation/translation, shear bị từ chối.

Gói bàn giao `output/HopBanChaiDien` có cùng script SHA256 với hai native layout variants: `0ee8b8101230f2178b4c4d51129bd38b37bfe97cf6453894e04c12bde36eb322`. ZIP `dist/HopBanChaiDien-fusion.zip` chứa5file, CRC và byte của script đã đối chiếu. Source SHA256 và source project status được kiểm tra lại, giữ nguyên.

Cả4đối chiếu mesh suite012 đạt ngưỡng bounds/surface0.05mm và volume/symmetricdifference0.5%. Giá trị lớn nhất: bounds0.000012208mm, sampled bidirectional surface0.003197914mm, relative volume0.006136842%, relative symmetricdifference0.047377834%. Mọi mesh kín và số component khớp reference.

| Case | Components | Vòng kín tại Z1.5 / Z75 / Z205 / Y0.123 |
| --- | ---: | --- |
| layout baseline | 2 | 21 / 4 / 2 / 5 |
| layout height_resize | 2 | 21 / 4 / 2 / 5 |
| body_custom | 1 | 8 / 2 / 2 / 4 |
| assembled | 1 | 20 / 2 / 4 / 3 |

Các số vòng của native/reference khớp từng mặt cắt; body_custom có7lỗ đáy cộng outline ngoài tạiZ1.5. Compact evidence: [4native cases](validation/toothbrush-native-validation.json), [15native regression cases](validation/toothbrush-regression.json), [4geometry comparisons](validation/toothbrush-geometry-comparison.json), [artifact manifest](validation/toothbrush-artifact-manifest.json). File mesh/STEP lớn và bằng chứng trung gian giữ trong `work/evidence`.

Kiểm chứng vật lý, lực vặn/độ bền ren và máy Fusion thứ hai giữ trạng thái `not_run`.
