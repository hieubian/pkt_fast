# SimuLAN Studio

Trình thiết kế và mô phỏng sơ đồ mạng chạy trên trình duyệt, giao diện viết lại theo phong cách Apple, có xuất file Cisco Packet Tracer `.pkt`.

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

> > Nếu chỉ mở `index.html` trực tiếp, thiết kế và mô phỏng vẫn chạy; chức năng xuất cần API nên hãy dùng `server.py`.

## Đưa lên GitHub và Vercel

1. Giải nén ZIP và đẩy **nội dung thư mục dự án** vào repository mới trên GitHub.
2. Trong Vercel, chọn **Add New → Project**, rồi import repository đó.
3. Để Root Directory ở thư mục gốc; không cần build command. Vercel phục vụ `index.html` và nhận `api/export.py` làm Python Function.
4. Sau khi deploy, mở URL Vercel và thử **Xuất .pkt** với lab cơ bản.

Vercel cài thư viện từ `requirements.txt`. Python runtime mặc định được ghim ở 3.12 qua `.python-version`.

## Dùng nhanh

- Kéo PC, Laptop, Switch hoặc Router từ thanh bên trái vào sơ đồ (hoặc bấm để thêm).
- Nối dây: kéo chấm xanh ở mép thiết bị sang thiết bị kia, hoặc chọn **Nối dây** (`C`). Cổng được gán tự động; chọn dây để đổi cổng.
- **Ping** (`P`): chọn PC/Laptop nguồn rồi bấm thiết bị đích. Kết quả hiện từng bước ARP, định tuyến, ACL.
- Switch: tạo VLAN, đặt từng cổng Access/Trunk. Router: nhập IP từng cổng, thêm subinterface theo VLAN (router-on-a-stick).
- `⌘Z` / `⇧⌘Z` hoàn tác, `Delete` xóa, `Esc` thoát chế độ. Sơ đồ tự lưu trong trình duyệt; **Lưu**/**Mở** dùng tệp JSON.
- **Xuất .pkt**: kiểm tra, rồi tạo file Packet Tracer.

## Mô phỏng

Bộ mô phỏng theo đúng thứ tự mạng thật: host so sánh subnet, ARP tới đích hoặc gateway, switch chuyển khung theo VLAN (access/trunk, native VLAN 1, khung có tag bị chặn ở cổng access), router định tuyến giữa các interface đã cấu hình, ACL chặn ở chiều vào, gói trả lời cũng bị kiểm tra ACL. Chưa có định tuyến tĩnh/động nên chỉ định tuyến giữa các mạng nối trực tiếp với một router.

## Hỗ trợ xuất

| Trong SimuLAN | Kết quả trong file Packet Tracer |
|---|---|
| PC, Laptop | PC-PT |
| Router 2911 hoặc 2811 | Router đã chọn, tự gán cổng tương ứng |
| Switch | Switch mặc định của pktlib, cổng FastEthernet |
| VLAN access/trunk | Cấu hình IOS trên switch |
| IP, subnet, gateway | Cấu hình host hoặc interface router |
| Subinterface có VLAN | encapsulation dot1Q và IP |
| ACL chặn | Extended ACL áp dụng inbound trên các cổng router |

Thư viện thiết bị chỉ gồm loại xuất được, nên mọi thứ trên sơ đồ đều có trong file .pkt.

## Kiểm thử

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Thư viện và giấy phép

Giao diện được sửa đổi từ [SimuLAN](https://github.com/mrpiay/SimuLAN) của MrPiay, phát hành theo MIT. Giữ file `LICENSE` khi fork hoặc phân phối.

File `.pkt` được tạo bằng [pktlib](https://pypi.org/project/pktlib/), một dự án độc lập, không liên kết với Cisco. pktlib nêu phiên bản Packet Tracer 8.2.0 là môi trường đã kiểm thử; hãy mở file bằng bản Packet Tracer bạn đang dùng để xác nhận tương thích.

