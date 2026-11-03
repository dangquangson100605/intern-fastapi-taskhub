# Tiến Độ Dự Án: TaskHub

Tài liệu này theo dõi toàn bộ tiến độ 14 tính năng và lịch sử thực hiện qua từng ngày trong lộ trình 8 ngày. Mỗi ngày hoàn thành sẽ được ghi nhật ký nối tiếp ở phía dưới.

---

## 1. Bảng theo dõi 14 tính năng bắt buộc (Dashboard Hiện Tại)

| # | Tính năng | Kế hoạch | Trạng thái hiện tại | Ghi chú / Bằng chứng |
|---|---|---|---|---|
| 1 | Auth (Register, Login, Refresh, Logout) | Ngày 3 | 🟢 Hoàn thành 100% | Đã triển khai bcrypt, JWT access/refresh token, Redis token blacklist |
| 2 | User (Profile, Update, Password) | Ngày 1, 3, 7 | 🟢 Hoàn thành CRUD + Profile | Đã có `GET /users/me`, `PATCH /users/me`, mật khẩu băm bcrypt |
| 3 | Workspace CRUD + Members | Ngày 4 | 🟢 Đã tạo bảng DB | Bảng `workspaces`, `workspace_members` đã có trong DB |
| 4 | Project CRUD + Archive | Ngày 4 | 🟢 Đã tạo bảng DB | Bảng `projects` đã có trong DB |
| 5 | Task CRUD + Assign + Status + Priority | Ngày 5 | 🟢 Đã tạo bảng DB | Bảng `tasks` đã có trong DB |
| 6 | Label CRUD + Gán/bỏ label | Ngày 5 | 🟢 Đã tạo bảng DB | Bảng `labels`, `task_labels` đã có trong DB |
| 7 | Comment CRUD | Ngày 5 | 🟢 Đã tạo bảng DB | Bảng `comments` đã có trong DB |
| 8 | Filter & Pagination | Ngày 5 | 🟢 Đã test thành công trên User | Phân trang `page`, `limit`, `total`, `total_pages` chạy chuẩn |
| 9 | Redis Caching + Invalidation | Ngày 6 | ⏳ Chưa bắt đầu | Chờ xong Task CRUD |
| 10 | Background Task (Email notification) | Ngày 6 | ⏳ Chưa bắt đầu | Chờ xong Task assign |
| 11 | RBAC (Admin, Owner, Editor, Viewer) | Ngày 4 | 🟡 Sẵn sàng triển khai Ngày 4 | Role Enums và JWT claim đã tích hợp |
| 12 | Swagger / ReDoc Documentation | Ngày 7 | 🟢 Hoạt động mượt mà | BearerAuth scheme với nút Authorize đã hiển thị |
| 13 | Docker Compose | Ngày 7 | ⏳ Chưa bắt đầu | Chưa tạo Dockerfile / docker-compose.yml |
| 14 | Code Quality (Ruff & mypy pass) | Ngày 8 | 🟢 Pass 100% | Ruff & Mypy pass sạch sẽ trên toàn bộ các file Auth & Security |

---

## 2. Lộ trình tổng thể 8 ngày

- [x] **Ngày 1: Core Setup & Architecture** (Hoàn thành khung kiến trúc, commit `253cbb7`)
- [x] **Ngày 2: Database — SQLAlchemy 2.x & Alembic** (Hoàn thành 100%: 8 bảng DB, async migration, commit `dd3247f`)
- [x] **Ngày 3: Authentication & Security** (Hoàn thành 100%: Register, Login, Refresh, Logout, Redis Blacklist, `get_current_user`, `/users/me`)
- [ ] **Ngày 4: RBAC & Workspace / Project CRUD** (Mục tiêu tiếp theo)
- [ ] **Ngày 5: Task, Label, Comment CRUD + Filter & Pagination**
- [ ] **Ngày 6: Caching, Background Tasks & Middleware**
- [ ] **Ngày 7: Docker, Configuration & API Documentation**
- [ ] **Ngày 8: Review, Refactor & Optimization**

---

## 3. Nhật ký tiến độ chi tiết qua từng ngày (Daily Progress Logs)

### 📌 Ngày 1: Core Setup & Architecture (30/10/2026)
- **Mục tiêu:** Dựng khung kiến trúc phân tầng Layered Architecture và luồng in-memory CRUD ban đầu.
- **Kết quả thực hiện:**
  - Khởi tạo thư mục dự án: `app/api`, `app/core`, `app/models`, `app/repositories`, `app/schemas`, `app/services`.
  - Viết `app/main.py`, `app/core/config.py` đọc `.env`, `app/core/database.py`, `app/core/dependencies.py`.
  - Định nghĩa 8 SQLAlchemy models trong `app/models/`.
  - Xây dựng `BaseRepository[T]`, `UserRepository`, `UserService`, `UserSchemas`.
  - Đóng gói commit: `253cbb7`.

### 📌 Ngày 2: Database — SQLAlchemy 2.x & Alembic (31/10/2026)
- **Mục tiêu:** Nối Database thật, cấu hình Alembic async, migration tạo 8 bảng và kiểm thử User CRUD với MySQL.
- **Kết quả thực hiện:**
  - Sửa dứt điểm 16 lỗi Mypy trong `app/models/` bằng `if TYPE_CHECKING:`.
  - Đăng ký toàn bộ 8 models trong `app/models/__init__.py`.
  - Khởi tạo `alembic init -t async alembic`, cấu hình `alembic/env.py` hỗ trợ dynamic `DATABASE_URL` và `Base.metadata`.
  - Xử lý mã hóa URL `quote_plus` và escape `%` thành `%%` cho `configparser`.
  - Sinh migration `3d1d3666a267_create_all_tables.py` và áp dụng `alembic upgrade head` tạo 8 bảng trong MySQL `taskhub`.
  - Kiểm thử Swagger UI: Tạo 2 user thật trong DB, test 409 Conflict trùng email, test 422 Pydantic validation, test 200 GET phân trang.
  - Đóng gói commit: `dd3247f`.

### 📌 Ngày 3: Authentication & Security (03/11/2026)
- **Mục tiêu:** Xây dựng hệ thống xác thực người dùng đầy đủ với bcrypt, JWT access/refresh token, Redis token blacklist và route cá nhân.
- **Kết quả thực hiện:**
  - Tạo `app/core/security.py`: Hashing mật khẩu bằng `bcrypt` trực tiếp, tạo/giải mã JWT access/refresh token.
  - Tạo `app/core/redis.py`: Async Redis client, quản lý token blacklist khi logout với in-memory fallback.
  - Tạo `app/schemas/auth.py` và `app/services/auth.py`: Nghiệp vụ `register`, `login`, `refresh_token`, `logout`.
  - Tạo `app/api/v1/endpoints/auth.py`: 4 endpoint auth (/register, /login, /refresh, /logout).
  - Cập nhật `app/core/dependencies.py`: Tích hợp `HTTPBearer` scheme cho Swagger UI và dependency `get_current_user`.
  - Cập nhật `app/api/v1/endpoints/users.py`: Thêm `GET /users/me` và `PATCH /users/me`.
  - Cập nhật `app/services/user.py`: Băm mật khẩu bcrypt khi tạo user.
  - Kiểm thử: Mypy 100% pass (9 source files), Ruff clean 100%.

---

## 4. Ba việc ưu tiên tiếp theo (Cho Ngày 4: RBAC & Workspace/Project CRUD)
1. **RBAC Dependencies (`app/core/permissions.py`):** Viết dependency kiểm tra vai trò người dùng trong workspace (`OWNER`, `EDITOR`, `VIEWER`) và hệ thống (`ADMIN`).
2. **Workspace Management:** Repository, Service, Schemas và Endpoints cho Workspace (CRUD, thêm/xóa thành viên).
3. **Project Management:** Repository, Service, Schemas và Endpoints cho Project thuộc Workspace (CRUD, Archive project).
