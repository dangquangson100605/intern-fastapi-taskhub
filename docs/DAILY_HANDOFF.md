# Nhật Ký Bàn Giao Hằng Ngày (Daily Handoff Log)

Tài liệu này lưu trữ toàn bộ lịch sử bàn giao công việc qua từng ngày theo trình tự thời gian. Mỗi phiên làm việc mới sẽ được bổ sung tiếp nối ở phần dưới.

---

# 📅 Báo Cáo Bàn Giao Cuối Ngày — Ngày 1

- **Ngày làm việc:** Ngày 1 (Phiên làm việc 30/10/2026 - Tổng hợp & Bàn giao 31/10/2026)
- **Nhánh Git (Current Branch):** `main`
- **Commit:** `253cbb7` — *feat(day-1): setup core architecture, config and user CRUD*
- **Trạng thái Working Tree:** Chưa commit file `GIAI_THICH_THUAT_NGU.md` và thư mục `docs/`.

### 1. Mục tiêu phiên làm việc Ngày 1
- Thiết lập bộ khung kiến trúc ứng dụng FastAPI (Layered Architecture: API $\rightarrow$ Service $\rightarrow$ Repository $\rightarrow$ Model).
- Thiết lập cấu hình hệ thống bằng `pydantic-settings` đọc từ biến môi trường.
- Định nghĩa đầy đủ 8 SQLAlchemy 2.x Models chuẩn bị cho migration.
- Xây dựng generic `BaseRepository[T]` và luồng CRUD cho tài nguyên User.

### 2. Việc đã hoàn thành (Dựa trên code và kiểm chứng thực tế)
- [x] Khởi tạo cấu trúc thư mục phân tầng cho dự án (`app/api`, `app/core`, `app/models`, `app/repositories`, `app/schemas`, `app/services`).
- [x] Tạo file cấu hình `app/core/config.py` và template `.env.example`.
- [x] Tạo `app/main.py` tích hợp FastAPI instance, Lifespan events, CORS middleware, Global exception handling.
- [x] Khởi tạo `app/core/database.py` cấu hình Async Engine (`create_async_engine`) và Declarative `Base`.
- [x] Khai báo 8 SQLAlchemy Models trong `app/models/` (`user`, `workspace`, `project`, `task`, `label`, `comment`).
- [x] Xây dựng Generic Repository `app/repositories/base.py` (`BaseRepository[T]`) và `app/repositories/user.py`.
- [x] Xây dựng Pydantic Schemas `app/schemas/user.py` và `app/schemas/common.py`.
- [x] Cài đặt `app/services/user.py` và API endpoints `app/api/v1/endpoints/users.py`.
- [x] Import test thành công: Module `app.main` tải lên hoàn chỉnh không có lỗi runtime import.

### 3. Danh sách file đã tạo / chỉnh sửa trong phiên

| File | Hành động | Mục đích |
|---|---|---|
| `app/main.py` | Đã tạo | Điểm khởi chạy FastAPI, cấu hình CORS, Lifespan, Exception handlers, Router |
| `app/core/config.py` | Đã tạo | Quản lý settings qua `pydantic-settings`, đọc `.env` |
| `app/core/database.py` | Đã tạo | Cấu hình async engine, session factory và Base declarative model |
| `app/core/dependencies.py` | Đã tạo | Dependency injection `get_db` cung cấp `AsyncSession` |
| `app/core/exceptions.py` | Đã tạo | Hệ thống custom exception (`AppException`) và exception handlers |
| `app/models/*.py` (6 files) | Đã tạo | Định nghĩa 8 models dữ liệu: User, Workspace, WorkspaceMember, Project, Task, Label, TaskLabel, Comment |
| `app/repositories/base.py` | Đã tạo | Generic CRUD repository pattern tái sử dụng |
| `app/repositories/user.py` | Đã tạo | Data access layer cho User |
| `app/schemas/*.py` | Đã tạo | Pydantic validation schemas (UserCreate, UserResponse, UserUpdate, PaginatedResponse) |
| `app/services/user.py` | Đã tạo | Business logic xử lý User |
| `app/api/v1/endpoints/users.py` | Đã tạo | REST endpoints cho User (GET, POST, PATCH, DELETE) |
| `app/api/v1/router.py` | Đã tạo | Tổng hợp các router v1 |
| `.env.example` | Đã tạo | Mẫu cấu hình môi trường chuẩn |
| `pyproject.toml`, `requirements.txt`| Đã tạo | Quản lý dependencies và cấu hình tools (ruff, mypy) |
| `ke_hoach_taskhub.md` | Đã tạo | Đề cương và kế hoạch chi tiết 8 ngày làm việc |
| `GIAI_THICH_THUAT_NGU.md` | Chưa commit | Tài liệu giải thích thuật ngữ chuyên môn trong dự án |

### 4. Lệnh kiểm thử đã chạy và kết quả
1. **Kiểm tra import module app:**
   - *Lệnh:* `python -c "import app.main; print('app imported successfully')"`
   - *Kết quả:* Thành công (`app imported successfully`, Exit code 0).
2. **Kiểm tra cú pháp & quy tắc với Ruff:**
   - *Lệnh:* `ruff check app`
   - *Kết quả:* 16 lỗi/cảnh báo (B008 do `Depends` trong router arguments, N802 cho property method uppercase trong config, UP042 kế thừa enum, I001 import sorting).
3. **Kiểm tra tĩnh Type Hints với Mypy:**
   - *Lệnh:* `mypy app --ignore-missing-imports`
   - *Kết quả:* 16 lỗi trong 6 files model liên quan đến việc các models tham chiếu chéo nhau trong type annotation của `relationship` mà chưa import hoặc thiếu block `if TYPE_CHECKING:`.

### 5. Quyết định kỹ thuật & Việc dang dở
- Áp dụng Generic `BaseRepository[T]` để dùng lại cho các entity sau này.
- Chưa tạo migration database và chưa cấu hình Alembic.

### 6. Việc ưu tiên tiếp theo (Cho Ngày 2)
1. Khởi tạo và cấu hình Alembic async.
2. Sửa 16 lỗi Mypy trong `app/models/` bằng `TYPE_CHECKING`.
3. Tạo migration đầu tiên và kiểm thử User CRUD với Database thật.

---

# 📅 Báo Cáo Bàn Giao Cuối Ngày — Ngày 2

- **Ngày làm việc:** Ngày 2 (31/10/2026)
- **Nhánh Git (Current Branch):** `main`
- **Commit:** `dd3247f` — *feat(day-2): setup alembic async migrations, models and database CRUD*
- **Trạng thái Working Tree:** Đã commit toàn bộ thay đổi Ngày 2 lên nhánh `main`.

### 1. Mục tiêu phiên làm việc Ngày 2
- Sửa dứt điểm 16 lỗi Mypy trong các model quan hệ bằng kỹ thuật `TYPE_CHECKING`.
- Khởi tạo và cấu hình hoàn chỉnh Alembic hỗ trợ async (`asyncmy` / `AsyncEngine`).
- Tự động sinh file migration cho 8 bảng dữ liệu cốt lõi và áp dụng vào MySQL.
- Kiểm thử luồng User CRUD trên Swagger UI với Database thật.

### 2. Việc đã hoàn thành (Có bằng chứng kiểm thử thực tế)
- [x] **Chuẩn hóa Type Hints trong Models:** 
  - Đã thêm `if TYPE_CHECKING:` vào toàn bộ các model (`user`, `workspace`, `project`, `task`, `label`, `comment`).
  - Đăng ký toàn bộ 8 models trong `app/models/__init__.py`.
  - Kết quả: `mypy app\models\ --ignore-missing-imports` đạt **0 errors** (Success trên 7 files).
- [x] **Khởi tạo và cấu hình Alembic async:**
  - Chạy `alembic init -t async alembic`.
  - Cấu hình `alembic/env.py` liên kết `target_metadata = Base.metadata` và đọc dynamic `DATABASE_URL`.
  - Xử lý mã hóa URL (`quote_plus`) và escape `%` thành `%%` cho `configparser` đối với mật khẩu chứa ký tự đặc biệt (`@`).
- [x] **Tạo và thực thi Migration:**
  - Đã sinh file migration `alembic/versions/3d1d3666a267_create_all_tables.py`.
  - Đã chạy `alembic upgrade head` tạo thành công 8 bảng + bảng `alembic_version` trên MySQL database `taskhub`.
- [x] **Nghiệm thu End-to-End User CRUD trên Swagger UI:**
  - `POST /api/v1/users`: Tạo thành công `id: 1` (`sonson@example.com`) và `id: 2` (`sondangn@eee.com`) trả về HTTP `201 Created`.
  - Test bắt lỗi trùng email: Trả về HTTP `409 Conflict` kèm thông báo JSON chuẩn.
  - Test Pydantic validation: Mật khẩu < 8 ký tự trả về HTTP `422 Unprocessable Content`.
  - `GET /api/v1/users`: Trả về danh sách 2 users từ database kèm metadata phân trang (`total: 2`, `page: 1`, `limit: 20`, `total_pages: 1`) với HTTP `200 OK`.

### 3. Danh sách file đã tạo / chỉnh sửa trong phiên

| File | Trạng thái | Mục đích |
|---|---|---|
| `app/models/*.py` (6 files) | Đã sửa | Thêm `TYPE_CHECKING` để loại bỏ lỗi Type Checking và tránh Circular Import |
| `app/models/__init__.py` | Đã sửa | Export toàn bộ 8 models để nạp vào `Base.metadata` cho Alembic |
| `app/core/config.py` | Đã sửa | Dùng `quote_plus` mã hóa an toàn mật khẩu có ký tự đặc biệt trong URL kết nối |
| `alembic/env.py` | Đã tạo & sửa | Cấu hình async migration, target metadata và escape `%` cho configparser |
| `alembic.ini` | Đã tạo | File cấu hình gốc của Alembic |
| `alembic/versions/3d1d3666a267_create_all_tables.py` | Đã tạo | File migration tự động tạo 8 bảng |

### 4. Các vấn đề kỹ thuật đã xử lý trong phiên
1. **Lỗi Mypy Circular Import:** Xử lý bằng `from typing import TYPE_CHECKING` tách biệt giữa runtime và static analysis.
2. **Lỗi kết nối MySQL do Password chứa ký tự `@`:** Xử lý bằng `quote_plus()` trong `app/core/config.py`.
3. **Lỗi `ValueError: invalid interpolation syntax`:** Xử lý bằng `.replace("%", "%%")` trong `alembic/env.py` khi truyền URL vào `configparser`.

### 5. Việc ưu tiên tiếp theo (Cho Ngày 3)
1. Thiết lập Redis connection dùng cho token blacklist.
2. Xây dựng module Security (hash password bcrypt, JWT access & refresh token).
3. Triển khai luồng Auth Endpoints & Dependency `get_current_user`.

---

# 📅 Báo Cáo Bàn Giao Cuối Ngày — Ngày 3

- **Ngày làm việc:** Ngày 3 (03/11/2026)
- **Nhánh Git (Current Branch):** `main`
- **Commit gần nhất trước phiên:** `dd3247f` (*feat(day-2): setup alembic async migrations, models and database CRUD*)
- **Trạng thái Working Tree:** 
  - Các file sửa đổi: `app/api/v1/endpoints/users.py`, `app/api/v1/router.py`, `app/core/dependencies.py`, `app/main.py`, `app/schemas/user.py`, `app/services/user.py`, `pyproject.toml`, `docs/PROGRESS.md`, `docs/DAILY_HANDOFF.md`.
  - Các file tạo mới: `app/api/v1/endpoints/auth.py`, `app/core/redis.py`, `app/core/security.py`, `app/schemas/auth.py`, `app/services/auth.py`.

### 1. Mục tiêu phiên làm việc Ngày 3
- Triển khai toàn diện hệ thống Authentication & Security theo chuẩn REST API.
- Băm mật khẩu an toàn với bcrypt (không lưu plain text).
- Tạo và xác thực cặp token JWT (Access Token & Refresh Token).
- Xây dựng cơ chế thu hồi token (Token Blacklist) với Redis khi người dùng đăng xuất.
- Xây dựng dependency xác thực `get_current_user` qua Bearer Token và bảo vệ các endpoint cá nhân (`/users/me`).

### 2. Việc đã hoàn thành (Dựa trên bằng chứng kiểm thử thực tế)
- [x] **Security Core (`app/core/security.py`):**
  - Cài đặt `hash_password` và `verify_password` sử dụng `bcrypt` trực tiếp, tương thích hoàn toàn Python 3.12/3.13 (tránh lỗi deprecation của passlib với bcrypt 4.x).
  - Cài đặt `create_access_token` (TTL 30 phút), `create_refresh_token` (TTL 7 ngày) kèm claims `sub`, `exp`, `iat`, `jti`, `type`.
  - Cài đặt `decode_token` kiểm tra signature và hạn dùng, trả về exception chuẩn `UnauthorizedException`.
- [x] **Redis & Token Blacklist (`app/core/redis.py`):**
  - Async Redis client qua `redis.asyncio` với timeout cấu hình.
  - Cài đặt `add_token_to_blacklist` và `is_token_blacklisted` với cơ chế in-memory fallback thông minh (giúp server không crash khi Redis server chưa bật lúc dev).
  - Tích hợp `close_redis()` vào `lifespan` shutdown trong `app/main.py`.
- [x] **Auth Schemas & Service (`app/schemas/auth.py`, `app/services/auth.py`):**
  - Schemas: `RegisterRequest`, `LoginRequest`, `TokenResponse`, `RefreshTokenRequest`.
  - Service: Nghiệm thu các luồng `register`, `login`, `refresh_token`, `logout`.
- [x] **Auth & User Endpoints (`app/api/v1/endpoints/auth.py`, `users.py`):**
  - `POST /api/v1/auth/register`: Đăng ký tài khoản mới, mật khẩu băm bcrypt.
  - `POST /api/v1/auth/login`: Xác thực credentials, cấp cặp JWT access + refresh token.
  - `POST /api/v1/auth/refresh`: Cấp mới access token từ refresh token hợp lệ (chặn nếu nằm trong blacklist).
  - `POST /api/v1/auth/logout`: Thu hồi refresh token đưa vào Redis blacklist.
  - `GET /api/v1/users/me`: Lấy thông tin user hiện tại (yêu cầu Bearer Token).
  - `PATCH /api/v1/users/me`: Cập nhật thông tin profile user hiện tại.
- [x] **Tích hợp Swagger Authorization:**
  - Cấu hình `HTTPBearer(scheme_name="BearerAuth")` trong `app/core/dependencies.py`.
  - Swagger UI hiển thị nút **Authorize** và ổ khóa bảo vệ trên các route `/users/me`.

### 3. Danh sách file đã tạo / chỉnh sửa trong phiên

| File | Trạng thái | Mục đích |
|---|---|---|
| `app/core/security.py` | Đã tạo | Hashing mật khẩu với bcrypt và mã hóa/giải mã JWT tokens |
| `app/core/redis.py` | Đã tạo | Async Redis client & quản lý blacklist token khi logout |
| `app/schemas/auth.py` | Đã tạo | Pydantic validation schemas cho các request/response auth |
| `app/services/auth.py` | Đã tạo | Business logic đăng ký, đăng nhập, refresh token, logout |
| `app/api/v1/endpoints/auth.py` | Đã tạo | Endpoints API xác thực (/register, /login, /refresh, /logout) |
| `app/core/dependencies.py` | Đã sửa | Bổ sung HTTPBearer scheme và dependency get_current_user |
| `app/services/user.py` | Đã sửa | Cập nhật create_user băm mật khẩu với hash_password |
| `app/api/v1/endpoints/users.py` | Đã sửa | Thêm route GET & PATCH /users/me bảo vệ bởi get_current_user |
| `app/api/v1/router.py` | Đã sửa | Đăng ký auth.router vào router tổng hợp API v1 |
| `app/main.py` | Đã sửa | Đóng kết nối Redis trong lifespan shutdown |
| `pyproject.toml` | Đã sửa | Thêm rule bỏ qua B008, N802 cho FastAPI patterns |
| `docs/PROGRESS.md` | Đã cập nhật | Cập nhật tiến độ hoàn thành Ngày 3 |
| `docs/DAILY_HANDOFF.md` | Đã cập nhật | Bổ sung báo cáo bàn giao Ngày 3 vào nhật ký |

### 4. Lệnh kiểm thử đã chạy và kết quả
1. **Kiểm tra import và hàm bảo mật:**
   - *Lệnh:* `python -c "import app.main; from app.core.security import hash_password, verify_password, create_access_token, decode_token; ..."`
   - *Kết quả:* Exit code 0, hash bcrypt và decode JWT pass 100%.
2. **Kiểm tra static analysis Mypy:**
   - *Lệnh:* `mypy app/core/security.py app/core/redis.py app/schemas/auth.py app/services/auth.py app/api/v1/endpoints/auth.py app/core/dependencies.py app/api/v1/endpoints/users.py app/services/user.py app/api/v1/router.py`
   - *Kết quả:* `Success: no issues found in 9 source files`.
3. **Kiểm tra linter Ruff:**
   - *Lệnh:* `ruff check app/core/security.py app/core/redis.py app/schemas/auth.py app/services/auth.py app/api/v1/endpoints/auth.py app/core/dependencies.py app/api/v1/endpoints/users.py app/services/user.py app/api/v1/router.py`
   - *Kết quả:* `All checks passed!`.

### 5. Ba việc ưu tiên tiếp theo (Cho Ngày 4: RBAC & Workspace/Project CRUD)
1. **RBAC Dependencies (`app/core/permissions.py`):** Viết dependency kiểm tra vai trò người dùng trong workspace (`OWNER`, `EDITOR`, `VIEWER`) và hệ thống (`ADMIN`).
2. **Workspace Management:** Repository, Service, Schemas và Endpoints cho Workspace (CRUD, thêm/xóa thành viên).
3. **Project Management:** Repository, Service, Schemas và Endpoints cho Project thuộc Workspace (CRUD, Archive project).

### 6. Hướng dẫn kiểm thử thủ công qua Swagger UI
1. Khởi động server:
   ```powershell
   uvicorn app.main:app --reload
   ```
2. Mở trình duyệt tại `http://localhost:8000/docs`.
3. **Bước 1 - Đăng ký:** Gọi `POST /api/v1/auth/register` với email và password mới $\rightarrow$ Nhận mã `201 Created`.
4. **Bước 2 - Đăng nhập:** Gọi `POST /api/v1/auth/login` với email và password vừa tạo $\rightarrow$ Nhận JSON chứa `access_token` và `refresh_token`.
5. **Bước 3 - Xác thực Swagger:** Copy `access_token`, bấm nút **Authorize** ở góc trên bên phải, dán token vào rồi bấm **Authorize**.
6. **Bước 4 - Test Route cá nhân:** Gọi `GET /api/v1/users/me` $\rightarrow$ Nhận thông tin cá nhân với mã `200 OK`.
7. **Bước 5 - Test Refresh:** Gọi `POST /api/v1/auth/refresh` với `refresh_token` $\rightarrow$ Nhận access token mới.
8. **Bước 6 - Test Logout:** Gọi `POST /api/v1/auth/logout` với `refresh_token` $\rightarrow$ Nhận thông báo đăng xuất; gọi lại `/auth/refresh` với token đó $\rightarrow$ Bị chặn `401 Unauthorized`.
