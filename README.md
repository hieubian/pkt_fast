# SimuLAN Studio

Trình thiết kế sơ đồ mạng chạy trên trình duyệt, dựa trên giao diện SimuLAN và bổ sung xuất file Cisco Packet Tracer `.pkt`.

## Chạy trên máy tính

Cần Python 3.10 trở lên.

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python server.py
```

Mở [http://127.0.0.1:8000](http://127.0.0.1:8000). Sơ đồ chạy trong trình duyệt; API chỉ nhận dữ liệu khi bạn bấm **Xuất .pkt**.

> Nếu chỉ mở `index.html` trực tiếp hoặc dùng `python -m http.server`, giao diện vẫn chạy nhưng chức năng xuất cần API. Dùng `server.py` để chạy cả hai phần.

## Đưa lên GitHub và Vercel

1. Giải nén ZIP và đẩy **nội dung thư mục dự án** vào repository mới trên GitHub.
2. Trong Vercel, chọn **Add New → Project**, rồi import repository đó.
3. Để Root Directory ở thư mục gốc; không cần build command. Vercel phục vụ `index.html` và nhận `api/export.py` làm Python Function.
4. Sau khi deploy, mở URL Vercel và thử **Xuất .pkt** với lab cơ bản.

Vercel cài thư viện từ `requirements.txt`. Python runtime mặc định được ghim ở 3.12 qua `.python-version`.

## Dùng nhanh

- Kéo PC, Router hoặc Switch vào vùng sơ đồ.
- Nối thiết bị bằng nút **Nối thiết bị** hoặc phím `C`.
- Cổng switch được gán tự động; có thể đổi cổng trong phần cấu hình VLAN của switch.
- Chọn router để đổi model 2911/2811 và cấu hình cổng.
- Nhập IP/CIDR, gateway, VLAN hoặc ACL. Cấu hình IP được lưu khi rời trường nhập.
- Chọn **Xuất .pkt**, xem phần kiểm tra, rồi tạo file.
- **Lưu sơ đồ** tải JSON về máy; đây là định dạng riêng để tiếp tục chỉnh sửa trong SimuLAN Studio.

## Hỗ trợ xuất

| Trong SimuLAN | Kết quả trong file Packet Tracer |
|---|---|
| PC, Laptop | PC-PT |
| Router 2911 hoặc 2811 | Router đã chọn, tự gán cổng tương ứng |
| Switch | Switch mặc định của pktlib, cổng FastEthernet |
| VLAN access/trunk | Cấu hình IOS trên switch |
| IP, subnet, gateway | Cấu hình host hoặc interface router |
| Router subinterface có VLAN | Cấu hình encapsulation dot1Q và IP |
| ACL deny | Extended ACL áp dụng inbound trên các cổng router |

Server, Printer, AP, Firewall và Cloud vẫn có trong mô phỏng SimuLAN nhưng chưa được chuyển sang thiết bị Packet Tracer. Màn hình kiểm tra sẽ báo rõ nếu sơ đồ còn loại thiết bị đó.

Cổng dây được chọn tự động bởi pktlib theo hai đầu kết nối. Các liên kết serial và cấu hình định tuyến nâng cao chưa có trong schema xuất hiện tại.

## Kiểm tra giao diện

Có thể chạy smoke test bằng Playwright nếu đã cài browser Chromium:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m unittest discover -s tests -p "test_*.py"
python tests/ui_smoke.py
```

Test dùng phản hồi .pkt giả để kiểm tra modal, preflight và thao tác tải file; nó không thay thế kiểm thử mở file bằng Packet Tracer.

## Thư viện và giấy phép

Giao diện được sửa đổi từ [SimuLAN](https://github.com/mrpiay/SimuLAN) của MrPiay, phát hành theo MIT. Giữ file `LICENSE` khi fork hoặc phân phối.

File `.pkt` được tạo bằng [pktlib](https://pypi.org/project/pktlib/), một dự án độc lập, không liên kết với Cisco. pktlib nêu phiên bản Packet Tracer 8.2.0 là môi trường đã kiểm thử; hãy mở file bằng bản Packet Tracer bạn đang dùng để xác nhận tương thích.

