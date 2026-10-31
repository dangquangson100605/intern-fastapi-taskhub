# Project Context: TaskHub (Task Management API)

## 1. Mục tiêu dự án
Xây dựng một hệ thống REST API backend quản lý công việc (tương tự mini Trello / Jira) theo chuẩn thực tế doanh nghiệp bằng **FastAPI** trong lộ trình 8 ngày làm việc (64 giờ).

Hệ thống cho phép:
- Quản lý không gian làm việc (**Workspace**), dự án (**Project**), công việc (**Task**), nhãn (**Label**), bình luận (**Comment**).
- Phân quyền theo vai trò (**RBAC**): `ADMIN`, `OWNER`, `EDITOR`, `VIEWER`.
- Xác thực bảo mật: JWT Access + Refresh token, Redis token blacklist.
- Tối ưu hiệu năng: Redis caching và Background task gửi email thông báo.

## 2. Kiến trúc hệ thống
Hệ thống áp dụng mô hình phân tầng **Layered Architecture**:
```
Client / Swagger UI
        │
        ▼
[API Layer / Endpoints] (app/api/v1/endpoints/)
        │   - Nhận HTTP request, validate schema Pydantic, phân quyền
        ▼
[Service Layer] (app/services/)
        │   - Chứa toàn bộ business logic, transaction, orchestration
        ▼
[Repository Layer] (app/repositories/)
        │   - Data access layer, thao tác ORM, generic BaseRepository[T]
        ▼
[Model Layer / Database] (app/models/ & MySQL/PostgreSQL)
            - SQLAlchemy 2.x Async ORM models & migrations
```

Cấu trúc thư mục chính:
```
taskhub/
├── app/
│   ├── api/v1/              # Routers & API endpoints
│   ├── core/                # Config, DB engine, security, dependencies, exceptions
│   ├── models/              # SQLAlchemy 2.x Declarative Base models
│   ├── repositories/        # Generic & specific data access repositories
│   ├── schemas/             # Pydantic v2 schemas (request/response)
│   ├── services/            # Business logic
│   └── main.py              # FastAPI app instance, lifespan, middleware
├── docs/                    # Tài liệu dự án, tiến độ & bàn giao
├── requirements.txt
├── pyproject.toml
└── .env.example
```

## 3. Tech Stack & Quyết định kỹ thuật cốt lõi
| Thành phần | Công nghệ lựa chọn | Lý do quyết định |
|---|---|---|
| **Framework** | FastAPI 0.111+ | Hiệu năng cao (ASGI), async native, tự động sinh OpenAPI / Swagger UI |
| **ORM** | SQLAlchemy 2.x (Async) | Chuẩn ORM mạnh mẽ của Python, hỗ trợ `AsyncSession`, `mapped_column` type-safe |
| **Driver DB** | `asyncmy` (MySQL 8) | Driver async native cho MySQL tương thích SQLAlchemy 2.x |
| **Migration** | Alembic | Quản lý vòng đời schema DB, tự động autogenerate migrations |
| **Validation** | Pydantic v2 & `pydantic-settings` | Tốc độ cao (viết bằng Rust), parse và validate type chặt chẽ, fail-fast env |
| **Caching & Blacklist** | Redis 7 | Tối ưu hóa truy vấn danh sách task và thu hồi refresh token nhanh chóng |
| **Code Quality** | Ruff & mypy | Linter siêu tốc và type checker đảm bảo chuẩn PEP 8 và type safety |

