# Thử converter với dustpan — 2026-10-16

**Kết quả: chưa chuyển được bằng converter tại commit `a1332ac`.** Lỗi đầu tiên ở dòng 53: `expected ']', got 'concat'`, tại list comprehension dùng `each concat(...)`. Chưa sinh package Python nên Fusion runtime và giới hạn lặp timeline của output mới đều là `not_run`.

Nguồn thử: `dustpan.scad`, SHA256 `9f8a284a37d630a114eb1b5773fc276a5a30d8fef1dacd14db03247d8cb54db2`. Cấu hình mặc định bật cả bốn gia cường; đơn vị mm. Source không có include/use/import. Giữ nguyên source, output và các chỉnh sửa đang có trong project nguồn. Dùng thư mục output mới và bàn giao bằng thư mục, không ZIP.

## Kiểm tra nguồn độc lập

OpenSCAD 2026.09.29, backend Manifold, xuất STL thành công: `Status: NoError`, genus 0, 10128 vertices, 20252 facets. Đọc lại STL bằng trimesh: một component kín, winding nhất quán; bounds `[-103,-100,0]` đến `[103,115,250]`, thể tích `284787.128994 mm³`. Đây là kiểm tra nguồn và mesh, chưa phải bằng chứng converter hoặc Fusion.

## Các giới hạn đã tái hiện riêng

Từng snippet độc lập được chạy qua `generate_package`; cả sáu bị từ chối:

| Ca thử | Kết quả thực tế |
| --- | --- |
| `[for(i=[0:2]) each [[i,0],[i,1]]]` | Parser: `expected ']', got ','` |
| `[for(i=[0:4]) if(i>1) [i,0]]` | Parser: `expected ']', got ','` |
| `multmatrix(...) linear_extrude(...)` | Frontend: `unsupported construct 'multmatrix'` |
| `linear_extrude(1) hull(){ ... }` | Frontend: `unsupported construct 'hull'` |
| `intersection(){ cube(2); translate([1,0,0]) cube(2); }` | Backend: `Unsupported solid operation intersection` |
| `linear_extrude(1) offset(delta=-0.2) polygon(...)` | Frontend: `unknown argument 'delta' for offset` |

Các lỗi và mesh thử giữ local tại `work/dustpan-converter-001/`. Không sao chép package Fusion dựng riêng có sẵn thành kết quả của converter; package đó có builder chuyên biệt và hồ sơ kiểm chứng độc lập.

## Hướng mở rộng theo phụ thuộc

1. Bổ sung ngữ nghĩa comprehension `each`/`if`, transform `multmatrix` và các operation còn thiếu với regression độc lập; parser đọc được chưa chứng minh dựng đúng geometry.
2. Khôi phục cung/đường tròn trên polygon, hull 2D của các đĩa và offset polygon. Dùng Extrude cho vùng thẳng, phép giao solid đúng ownership và sketch frame.
3. Nhận dạng các shell có tiết diện theo quy luật để dựng lòng khay, cove R5, đáy nâng quintic và vành theo vùng liên tục. Tránh biến từng lát cắt thành chuỗi feature dài; kiểm tra block lặp thực tế tối đa 5.
4. Đối chiếu các vùng chức năng, mặt cắt, bounds, thể tích và bề mặt với source hiện hành trước khi nhận bản native. Hồ sơ dựng riêng từng ghi global rim Loft khỏe trong Fusion nhưng sai export; dùng cảnh báo đó khi chọn cách dựng, không coi số feature thấp là bằng chứng độ khớp.

Phạm vi lượt thử này: tái hiện và chẩn đoán khả năng hiện tại, không thay source hay triển khai các extension trên. Native/STEP/F3D mới, thử tham số và in/lắp: `not_run`.
