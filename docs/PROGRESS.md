# Tiến Độ Dự Án: TaskHub

## 1. Bảng theo dõi tính năng (14 Features bắt buộc)

| # | Tính năng | Kế hoạch | Trạng thái hiện tại | Ghi chú / Bằng chứng |
|---|---|---|---|---|
| 1 | Auth (Register, Login, Refresh, Logout) | Ngày 3 | ⏳ Chưa bắt đầu | Mục tiêu phiên làm việc tiếp theo |
| 2 | User (Profile, Update, Password) | Ngày 1, 3, 7 | 🟢 Hoàn thành CRUD cơ bản trên DB | Đã kiểm thử thành công tạo & list users trên MySQL |
| 3 | Workspace CRUD + Members | Ngày 4 | 🟢 Đã tạo bảng DB | Bảng `workspaces`, `workspace_members` đã có trong DB |
| 4 | Project CRUD + Archive | Ngày 4 | 🟢 Đã tạo bảng DB | Bảng `projects` đã có trong DB |
| 5 | Task CRUD + Assign + Status + Priority | Ngày 5 | 🟢 Đã tạo bảng DB | Bảng `tasks` đã có trong DB |
| 6 | Label CRUD + Gán/bỏ label | Ngày 5 | 🟢 Đã tạo bảng DB | Bảng `labels`, `task_labels` đã có trong DB |
| 7 | Comment CRUD | Ngày 5 | 🟢 Đã tạo bảng DB | Bảng `comments` đã có trong DB |
| 8 | Filter & Pagination | Ngày 5 | 🟢 Đã test thành công trên User | Phân trang `page`, `limit`, `total`, `total_pages` chạy chuẩn |
| 9 | Redis Caching + Invalidation | Ngày 6 | ⏳ Chưa bắt đầu | Chờ xong Task CRUD |
| 10 | Background Task (Email notification) | Ngày 6 | ⏳ Chưa bắt đầu | Chờ xong Task assign |
| 11 | RBAC (Admin, Owner, Editor, Viewer) | Ngày 4 | 🟡 Đã có Enums trong DB | Migration sinh đúng kiểu Enum |
| 12 | Swagger / ReDoc Documentation | Ngày 7 | 🟢 Hoạt động mượt mà | Đã test trực tiếp qua Swagger UI `/docs` |
| 13 | Docker Compose | Ngày 7 | ⏳ Chưa bắt đầu | Chưa tạo Dockerfile / docker-compose.yml |
| 14 | Code Quality (Ruff & mypy pass) | Ngày 8 | 🟢 Models đạt 100% mypy pass | 7/7 file models không còn lỗi type |

---

## 2. Tiến độ theo ngày (Timeline 8 ngày)

- [x] **Ngày 1: Core Setup & Architecture** (Hoàn thành khung kiến trúc, commit `253cbb7`)
- [x] **Ngày 2: Database — SQLAlchemy 2.x & Alembic** (Hoàn thành 100%: 8 bảng DB, async migration, CRUD test OK)
- [ ] **Ngày 3: Authentication & Security** (Mục tiêu tiếp theo: JWT, bcrypt, Redis token blacklist, `get_current_user`)
- [ ] **Ngày 4: RBAC & Workspace / Project CRUD**
- [ ] **Ngày 5: Task, Label, Comment CRUD + Filter & Pagination**
- [ ] **Ngày 6: Caching, Background Tasks & Middleware**
- [ ] **Ngày 7: Docker, Configuration & API Documentation**
- [ ] **Ngày 8: Review, Refactor & Optimization**

---

## 3. Ba việc ưu tiên tiếp theo (Cho Ngày 3)
1. **Thiết lập Redis Connection:** Cấu hình kết nối Redis phục vụ lưu trữ blacklist refresh tokens khi logout.
2. **Xây dựng module Security (`app/core/security.py`):** Băm mật khẩu với bcrypt (`hash_password`, `verify_password`) và tạo/giải mã JWT tokens (`create_access_token`, `create_refresh_token`).
3. **Triển khai luồng Auth Endpoints & Dependency `get_current_user`:** Xây dựng Register, Login, Refresh, Logout và middleware bảo vệ các route riêng tư (`GET /users/me`).
