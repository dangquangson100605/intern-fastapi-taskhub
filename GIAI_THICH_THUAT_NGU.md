# 📖 Từ Điển & Cẩm Nang Giải Thích Thuật Ngữ — Dự Án TaskHub

> **Mục tiêu tài liệu này:** Giải thích mọi khái niệm, thuật ngữ kỹ thuật trong đề bài bằng **ngôn ngữ đời thường, hình ảnh hóa thực tế, dễ hiểu nhất**, không dùng văn phong hàn lâm.

---

## 📌 MỤC LỤC
1. [Web API & Các Khái Niệm Cơ Bản](#1-web-api--cac-khai-niem-co-ban)
2. [FastAPI & Python Có Gì Đặc Biệt?](#2-fastapi--python-co-gi-dac-biet)
3. [Mô Hình Kiến Trúc Dự Án (Layered Architecture)](#3-mo-hinh-kien-truc-du-an-layered-architecture)
4. [Database (Cơ Sở Dữ Liệu) & ORM](#4-database-co-so-du-lieu--orm)
5. [Authentication & Bảo Mật (Auth, JWT, RBAC)](#5-authentication--bao-mat-auth-jwt-rbac)
6. [Tối Ưu Hiệu Năng: Redis Cache & Background Tasks](#6-toi-uu-hieu-nang-redis-cache--background-tasks)
7. [Chuẩn Hóa Lỗi & Tài Liệu API](#7-chuan-hoa-loi--tai-lieu-api)
8. [Docker & Công Cụ Quản Lý Code](#8-docker--cong-cu-quan-ly-code)

---

## 1. Web API & Các Khái Niệm Cơ Bản

### 🍔 API (Application Programming Interface) là gì?
- **Hình dung thực tế:** Bạn vào một nhà hàng. Bạn là **Khách hàng** (Frontend / Web / App di động), nhà bếp là **Hệ thống dữ liệu** (Database). Bạn không thể tự tiện đi thẳng vào bếp xào nấu được. Bạn phải gọi **Người phục vụ** đưa thực đơn, nhận món từ bạn rồi mang vào bếp, sau đó bưng đĩa thức ăn ra cho bạn.
- **Trong lập trình:** **API chính là người phục vụ đó**. API nhận yêu cầu từ người dùng, kiểm tra tính hợp lệ, lấy dữ liệu rồi trả về kết quả dạng dữ liệu thô (thường là JSON).

### 🌐 RESTful API là gì?
- Là bộ quy tắc ngầm định quốc tế khi làm API, quy định cách đặt tên đường dẫn (URL) và hành động:
  - Tài nguyên luôn là **danh từ số nhiều**: `/users`, `/tasks`, `/projects`.
  - Không bao giờ đặt URL dạng động từ như `/get-users` hay `/delete-user`.

### 🔄 Các phương thức HTTP (HTTP Methods)
Thay vì đặt tên URL như `/create-task` hay `/delete-task`, REST API dùng chính các động từ chuẩn của giao thức mạng:

| Method | Ý nghĩa đời thường | Ví dụ TaskHub |
|---|---|---|
| **GET** | *“Cho tôi xem/lấy dữ liệu”* | `GET /tasks` (Lấy danh sách task) |
| **POST** | *“Tạo mới cho tôi cái này”* | `POST /tasks` (Tạo một task mới) |
| **PUT** | *“Thay thế đè toàn bộ thông tin này”* | `PUT /tasks/1` (Thay mới hoàn toàn task số 1) |
| **PATCH** | *“Chỉ sửa một vài trường thông tin thôi”* | `PATCH /tasks/1` (Chỉ đổi trạng thái từ "TODO" sang "DONE") |
| **DELETE** | *“Xóa cái này đi”* | `DELETE /tasks/1` (Xóa task số 1) |

### 🚦 Mã trạng thái HTTP (Status Codes)
Khi API trả về dữ liệu, nó luôn kèm theo một con số 3 chữ số để báo tình trạng:

- **2xx (Thành công tốt đẹp):**
  - `200 OK`: Thành công, trả về dữ liệu.
  - `201 Created`: Tạo mới thành công (thường dùng sau POST).
  - `204 No Content`: Xóa thành công, không cần trả về chữ nào nữa.
- **4xx (Lỗi do người dùng gửi sai):**
  - `400 Bad Request`: Dữ liệu gửi lên sai quy định chung.
  - `401 Unauthorized`: Chưa đăng nhập (chưa xuất trình vé/token).
  - `403 Forbidden`: Đã đăng nhập nhưng **không có quyền** (VD: Viewer đòi xóa task của Admin).
  - `404 Not Found`: Không tìm thấy (ID không tồn tại).
  - `422 Unprocessable Entity`: Dữ liệu sai định dạng (ví dụ: yêu cầu email nhưng bạn gửi chữ "abc", tuổi là số mà gửi chữ).
- **5xx (Lỗi tại máy chủ):**
  - `500 Internal Server Error`: Code backend bị crash (văng lỗi Exception chưa bắt).

---

## 2. FastAPI & Python Có Gì Đặc Biệt?

### ⚡ Async / Await (Bất đồng bộ) là gì?
- **Đồng bộ (Sync):** Giống nhân viên thu ngân phục vụ từng người một. Khi một khách đi ra xe tìm ví tiền (đang đợi Database đọc ổ đĩa), nhân viên đó đứng im đợi, cả hàng người phía sau phải chờ.
- **Bất đồng bộ (Async):** Trong lúc khách đi tìm ví (`await db.execute(...)`), nhân viên thu ngân lập tức nhận đơn của khách tiếp theo. Khi khách kia quay lại thì xử lý nốt. Nhờ vậy, server FastAPI có thể phục vụ **hàng nghìn người cùng lúc** mà không bị nghẽn.

### 💉 Dependency Injection (`Depends`) là gì?
- **Hình dung thực tế:** Bạn là thợ sửa xe. Thay vì mỗi lần sửa xe bạn phải tự đi rèn cờ-lê mỏ-lết, xưởng cơ khí đã "tiêm" (đưa sẵn) bộ đồ nghề vào tay bạn khi nhận ca.
- **Trong FastAPI:** Khi một hàm xử lý API cần kết nối Database (`session: AsyncSession = Depends(get_db)`) hay cần biết ai đang đăng nhập (`current_user = Depends(get_current_user)`), FastAPI sẽ tự động chạy hàm chuẩn bị sẵn và đưa kết quả vào tham số cho bạn dùng. Bạn không cần tự mở/đóng kết nối bằng tay.

### 🛡️ Pydantic v2 (Schema & Validation)
- Là "bảo vệ cổng ra vào" của dữ liệu:
  - **Request Body (Đầu vào):** Người dùng gửi dữ liệu lên, Pydantic kiểm tra: email có đúng đuôi `@gmail.com` không, password có dài hơn 8 ký tự không. Nếu sai, tự động chặn lại và trả lỗi `422`.
  - **Response Model (Đầu ra):** Dù trong Database có lưu mật khẩu đã băm (hashed_password), Pydantic giúp giấu trường đó đi, chỉ trả về cho client: `id, name, email`.

---

## 3. Mô Hình Kiến Trúc Dự Án (Layered Architecture)

Dự án TaskHub áp dụng mô hình 4 tầng phân công nhiệm vụ tách biệt:

```
[Người dùng gửi Request]
         │
         ▼
 1. CONTROLLER / ENDPOINTS  (app/api/v1/endpoints/...)
    • Người đứng quầy: Tiếp nhận request, đọc tham số, kiểm tra quyền cơ bản.
    • Chuyển tiếp công việc cho Service, KHÔNG tự ý tính toán hay đụng DB.
         │
         ▼
 2. SERVICE                 (app/services/...)
    • Bộ não nghiệp vụ: Xử lý logic logic kinh doanh (Business Logic).
    • Ví dụ: "Nếu task quá hạn thì không cho chuyển status", "Tạo task xong thì phải gửi email".
    • Cần dữ liệu gì thì gọi Repository.
         │
         ▼
 3. REPOSITORY              (app/repositories/...)
    • Thủ kho dữ liệu: Nơi duy nhất được quyền viết câu lệnh truy vấn Database.
    • Cung cấp các hàm sạch sẽ: `get_by_id`, `create`, `delete` để tầng Service gọi.
         │
         ▼
 4. MODEL                   (app/models/...)
    • Bản thiết kế (Bản vẽ): Định nghĩa các bảng trong Database (bảng User gồm những cột gì, Task gồm những cột gì).
```

👉 **Lợi ích:** Sau này muốn đổi từ MySQL sang PostgreSQL hay MongoDB, bạn chỉ cần sửa tầng Repository, toàn bộ logic nghiệp vụ ở tầng Service và Endpoint giữ nguyên!

---

## 4. Database (Cơ Sở Dữ Liệu) & ORM

### 🗄️ ORM (Object-Relational Mapping) là gì?
- **Cách cũ (SQL thuần):** Bạn phải viết tay câu chữ:
  ```sql
  SELECT * FROM users WHERE email = 'test@gmail.com';
  ```
  Rất dễ gõ nhầm chữ, dễ bị hack SQL Injection.
- **Dùng ORM (SQLAlchemy 2.x):** Bạn làm việc hoàn toàn bằng class và đối tượng Python:
  ```python
  stmt = select(User).where(User.email == "test@gmail.com")
  ```
  SQLAlchemy sẽ tự dịch câu lệnh Python này thành câu SQL tương ứng của MySQL/Postgres.

### 📜 Alembic (Database Migration) là gì?
- **Hình dung:** Giống như **Git dành riêng cho Database**.
- Khi bạn thêm một cột mới vào bảng (ví dụ: thêm cột `avatar_url` vào bảng `users`), bạn không nên mở phpMyAdmin hay DBeaver lên gõ lệnh sửa bằng tay, vì máy đồng đội hay máy chủ trên đám mây sẽ không có cột đó.
- Alembic giúp bạn sinh ra một file kịch bản lịch sử (migration script). Bất kỳ ai clone code về chỉ cần gõ `alembic upgrade head` là database của họ sẽ tự động được cập nhật cột mới y hệt bạn.

---

## 5. Authentication & Bảo Mật (Auth, JWT, RBAC)

### 🔑 Authentication (AuthN) vs Authorization (AuthZ)
- **Authentication (Xác thực):** *"Bạn là ai?"* (Đăng nhập bằng email + mật khẩu đúng hay sai).
- **Authorization (Phân quyền):** *"Bạn được phép làm gì?"* (Ví dụ: Bạn là Viewer thì không được phép xóa Project).

### 🏷️ JWT (JSON Web Token) hoạt động thế nào?
1. Người dùng gửi `email` + `password` lên server.
2. Server kiểm tra đúng, tạo ra một chuỗi mã hóa nhìn như mật mã (gọi là **JWT Token** giống như một tấm thẻ căn cước có dấu mộc đỏ kỹ thuật số).
3. Server gửi token này về cho người dùng.
4. Từ lần sau, mỗi khi gọi bất kỳ API nào, người dùng chỉ cần kẹp token này vào Header (`Authorization: Bearer <token>`). Server chỉ cần kiểm tra chữ ký của token là biết ngay người gửi là ai mà không cần query lại mật khẩu.

- **Access Token:** Thẻ ngắn hạn (sống 15 - 30 phút) để dùng hàng ngày.
- **Refresh Token:** Thẻ dài hạn (sống 7 ngày) được cất kỹ, chỉ dùng để xin cấp lại Access Token mới khi thẻ cũ hết hạn (giúp người dùng không phải gõ lại mật khẩu liên tục).
- **Token Blacklist (Danh sách đen):** Vì JWT bản chất không thể thu hồi trước hạn, nên khi người dùng bấm "Đăng xuất", ta lưu token đó vào Redis (Blacklist). Khi có request gửi lên, nếu token nằm trong blacklist thì từ chối ngay.

### 👥 RBAC (Role-Based Access Control)
- Phân quyền theo vai trò trong hệ thống TaskHub:
  - **Admin:** "Trùm cuối", xem và quản lý mọi user.
  - **Owner (Chủ Workspace):** Toàn quyền trong Workspace của mình (xóa workspace, mời/đuổi thành viên, tạo project).
  - **Editor:** Thành viên được làm việc (tạo task, sửa task, comment).
  - **Viewer:** Khách (chỉ được xem danh sách task, không có nút bấm sửa/xóa).

---

## 6. Tối Ưu Hiệu Năng: Redis Cache & Background Tasks

### ⚡ Caching (Redis) là gì?
- **Ví dụ:** Ai đó hỏi bạn *"1389 x 452 bằng bao nhiêu?"*. Lần đầu bạn phải lấy giấy bút ra nhân rất lâu (truy vấn Database tốn CPU, đọc ổ cứng). Sau khi tính ra `627,828`, bạn ghi luôn đáp án này lên miếng giấy nhớ dán trước mặt (lưu vào RAM của Redis). Lần sau ai hỏi lại câu đó, bạn liếc miếng giấy trả lời ngay trong 0.001 giây!
- Áp dụng trong TaskHub: Danh sách Task của một dự án được lưu vào Redis. Khi có hàng trăm người cùng mở xem bảng Kanban, server đọc thẳng từ RAM trả về cực nhanh. Khi ai đó sửa task thì mới xóa cache để lấy dữ liệu mới.

### 📬 Background Tasks (Tác vụ chạy ngầm)
- **Vấn đề:** Khi bạn bấm nút "Giao việc cho Nguyễn Văn A", hệ thống cần gửi 1 email thông báo cho anh A. Việc kết nối máy chủ gửi mail mất khoảng 2 - 3 giây. Nếu bắt người dùng ngồi nhìn màn hình xoay vòng 3 giây chỉ để chờ gửi mail thì trải nghiệm rất tệ.
- **Giải pháp:** API trả về ngay cho người dùng: *"Task đã tạo thành công (201 Created)"* chỉ sau 0.05 giây. Còn việc kết nối máy chủ gửi email thì giao cho Background Task thong thả chạy ngầm phía sau.

---

## 7. Chuẩn Hóa Lỗi & Tài Liệu API

### 📄 RFC 7807 (Problem Details)
- Khi API gặp lỗi, thay vì mỗi người trả về một kiểu lung tung, RFC 7807 là tiêu chuẩn quốc tế bắt buộc lỗi phải trả về theo định dạng chuẩn:
  ```json
  {
    "type": "https://api.taskhub.com/errors/not-found",
    "title": "Resource Not Found",
    "status": 404,
    "detail": "Task with ID 99 does not exist",
    "instance": "/api/v1/tasks/99"
  }
  ```

### 📚 Swagger UI & ReDoc
- FastAPI tự động đọc các file code và schema của bạn để tạo ra giao diện web trực quan:
  - **Swagger UI (`/docs`):** Cho phép bạn bấm thử (Try it out), nhập dữ liệu và xem kết quả API ngay trên trình duyệt mà không cần cài Postman.
  - **ReDoc (`/redoc`):** Bản tài liệu giao diện tĩnh chuyên nghiệp dành cho đối tác đọc tích hợp.

---

## 8. Docker & Công Cụ Quản Lý Code

### 🐳 Docker & Docker Compose
- **Câu nói kinh điển của lập trình viên:** *"Ơ sao trên máy em chạy bình thường mà sang máy anh lại lỗi?"* (Do khác phiên bản Python, thiếu cài thư viện hệ thống, sai múi giờ...).
- **Docker:** Đóng gói toàn bộ mã nguồn, Python, các thư viện cần thiết vào một "chiếc hộp" (Container). Mang chiếc hộp này sang máy tính Windows, Mac hay Linux trên máy chủ đều chạy giống hệt nhau 100%.
- **Docker Compose:** Một file kịch bản điều khiển dàn nhạc: chỉ bằng 1 câu lệnh `docker compose up`, nó tự động kéo và bật cùng lúc 3 chiếc hộp: App FastAPI + Database MySQL + Redis Caching.

### 🧹 Linter (Ruff) & Type Check (Mypy)
- **Ruff:** Như một người biên tập viên khó tính ngồi cạnh bạn. Bạn vừa gõ xong, Ruff tự động phát hiện: import thư viện mà không dùng, dòng quá dài, đặt tên biến sai chuẩn PEP8 và tự động format lại cho đẹp.
- **Mypy:** Kiểm tra kiểu dữ liệu tĩnh. Nếu hàm yêu cầu truyền vào số nguyên `task_id: int` mà bạn lỡ truyền chuỗi chữ `"abc"`, Mypy sẽ báo lỗi ngay trước khi bạn chạy code.

---

> 💡 **Mẹo:** Mỗi khi làm việc đến ngày nào trong kế hoạch 8 ngày, nếu gặp từ nào chưa rõ, bạn hãy mở lại file này tra cứu nhé!
