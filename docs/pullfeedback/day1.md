# Tổng Hợp Feedback & Cải Tiến Code Pull Request Day 1

Tài liệu này lưu trữ chi tiết toàn bộ các nhận xét của Giảng viên tại **Pull Request Day 1 (#1)**, kèm theo giải thích nguyên nhân, hướng giải quyết và đối chiếu mã nguồn trước/sau khi sửa.

---

## 1. Quy mô Pull Request & Cấu trúc Model

### Nhận xét nguyên văn của Giảng viên:
> *"PR 33 file hơi to, 5 model Workspace/Project/Task/Label/Comment chưa dùng ở Day 1 và PR #2 sửa lại gần hết, lần sau để model sang PR của ngày dùng tới."*

### Giải thích dễ hiểu:
- **Bản chất:** Day 1 yêu cầu thiết lập khung dự án và làm CRUD cơ bản cho User. Tuy nhiên, ở Day 1 ta đã định nghĩa trước toàn bộ 5 models khác (`Workspace`, `Project`, `Task`, `Comment`, `Label`) dù chưa hề có endpoint hay nghiệp vụ nào dùng đến chúng. Điều này khiến PR Day 1 bị phình to lên tới 33 file. Sang Day 2, ta lại phải mở cả 5 file này ra để sửa lại quan hệ và cấu hình index.
- **Quy chuẩn thực tế:** Trong quy trình phát triển phần mềm chuyên nghiệp, mỗi Pull Request chỉ nên chứa những file thực sự cần thiết để giải quyết tính năng của ngày hôm đó (Single Responsibility PR). Tránh tạo file thừa cho tương lai quá sớm.

### Hướng giải quyết:
- Rút kinh nghiệm cho các ngày tiếp theo: Chỉ commit và mở PR cho các tính năng đúng với scope của ngày làm việc đó.

---

## 2. Thiếu thư viện `email-validator` trong `requirements.txt`

### Nhận xét nguyên văn của Giảng viên:
> *"In requirements.txt: Dùng EmailStr mà thiếu email-validator, cài sạch theo README là app crash lúc import."*

### Giải thích dễ hiểu:
- **Bản chất:** Trong Pydantic, trường `EmailStr` không tự kiểm tra cú pháp email bằng code nội bộ mà bắt buộc phải phụ thuộc vào thư viện bên ngoài là `email-validator`. Nếu thiếu thư viện này trong `requirements.txt`, khi người khác clone dự án về máy mới và chạy lệnh cài đặt sạch theo hướng dẫn, ứng dụng sẽ bị crash ngay lúc khởi động (`ImportError`).

### Code trước khi sửa (`requirements.txt`):
```text
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
```

### Hướng giải quyết:
- Bổ sung `email-validator>=2.0.0` ngay dưới `pydantic`.
- Bổ sung `bcrypt>=4.0.0` để hỗ trợ mã hóa mật khẩu an toàn.

### Code sau khi sửa (`requirements.txt`):
```text
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
pydantic>=2.0.0
email-validator>=2.0.0
pydantic-settings>=2.0.0
...
passlib[bcrypt]>=1.7.4
bcrypt>=4.0.0
```

---

## 3. Quên ghi Log khi gặp lỗi 500 (`app/core/exceptions.py`)

### Nhận xét nguyên văn của Giảng viên:
> *"In app/core/exceptions.py: Handler 500 ko log exc, thêm logger.exception(...) trước khi trả response."*

### Giải thích dễ hiểu:
- **Bản chất:** Khi server gặp lỗi sập không lường trước (500), hàm bắt lỗi `generic_exception_handler` chỉ trả về câu thông báo lịch sự cho người dùng: *"An unexpected error occurred"*. Tuy nhiên trên màn hình terminal của lập trình viên hoặc file log, hệ thống lại im lặng, không ghi lại chi tiết lỗi (traceback) xảy ra ở file nào, dòng bao nhiêu. Hậu quả là lập trình viên không thể điều tra và sửa lỗi.

### Code trước khi sửa (`app/core/exceptions.py`):
```python
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "path": str(request.url),
        },
    )
```

### Hướng giải quyết:
- Import `from loguru import logger` và gọi `logger.exception("Unhandled server exception: {}", exc)` trước khi trả về `JSONResponse`.

### Code sau khi sửa (`app/core/exceptions.py`):
```python
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    logger.exception("Unhandled server exception: {}", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_ERROR",
            "message": ERROR_INTERNAL_SERVER,
            "path": str(request.url),
        },
    )
```

---

## 4. Lỗ hổng bảo mật CORS (`app/main.py`)

### Nhận xét nguyên văn của Giảng viên:
> *"In app/main.py: allow_origins=["*"] đi với allow_credentials=True thì Starlette echo mọi origin kèm credentials, đưa list origin vào Settings."*

### Giải thích dễ hiểu:
- **Bản chất:** `allow_origins=["*"]` cho phép bất kỳ trang web nào trên Internet được gửi request đến API của bạn. Nhưng khi đi kèm `allow_credentials=True` (cho phép gửi cookie/token đăng nhập), đây là một lỗ hổng bảo mật nghiêm trọng (chuẩn bảo mật web cấm wildcard `*` khi cho phép credentials). Trình duyệt Starlette sẽ tự động chấp nhận bất kỳ origin nào gửi lên kèm credentials, mở đường cho tấn công CSRF.

### Code trước khi sửa (`app/main.py`):
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Hướng giải quyết:
- Thêm biến `CORS_ORIGINS: list[str]` vào file `Settings` trong `app/core/config.py` để chỉ định danh sách domain tin cậy cụ thể (ví dụ: `http://localhost:3000`).
- Dùng `settings.CORS_ORIGINS` thay cho `["*"]`.

### Code sau khi sửa:
**Trong `app/core/config.py`:**
```python
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]
```

**Trong `app/main.py`:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 5. Cấu hình Fail-Fast nhưng lại gán sẵn giá trị mặc định (`app/core/config.py`)

### Nhận xét nguyên văn của Giảng viên:
> *"In app/core/config.py: Docstring ghi fail-fast mà field nào cũng có default, nhất là JWT_SECRET_KEY/DB_PASSWORD, bỏ default đi."*

### Giải thích dễ hiểu:
- **Bản chất:** Khái niệm "Fail-Fast" nghĩa là: nếu người dùng quên cấu hình file `.env` (thiếu mật khẩu DB hoặc mã khóa bí mật JWT), ứng dụng phải dừng ngay lập tức khi khởi động để cảnh báo. Việc gán giá trị mặc định như `JWT_SECRET_KEY = "change-me-in-production"` hay `DB_PASSWORD = ""` khiến app vẫn khởi động bình thường ngay cả khi không có cấu hình an toàn, dẫn đến nguy cơ lộ bảo mật nghiêm trọng trên môi trường production.

### Code trước khi sửa (`app/core/config.py`):
```python
    DB_PASSWORD: str = ""
    ...
    JWT_SECRET_KEY: str = "change-me-in-production"
```

### Hướng giải quyết:
- Xóa bỏ giá trị mặc định của `DB_PASSWORD: str` và `JWT_SECRET_KEY: str`. Khi khởi động, nếu thiếu 2 biến này trong `.env`, Pydantic sẽ lập tức báo lỗi và dừng ứng dụng (Fail-Fast thực sự).

### Code sau khi sửa (`app/core/config.py`):
```python
    DB_PASSWORD: str
    ...
    JWT_SECRET_KEY: str
```

---

## 6. Khai báo hằng số nhưng không sử dụng (`app/core/exceptions.py`)

### Nhận xét nguyên văn của Giảng viên:
> *"In app/core/exceptions.py: NotFoundException tự ghép f-string trong khi ERROR_USER_NOT_FOUND khai mà ko dùng; các default "Bad request"... cũng đưa vào constants."*

### Giải thích dễ hiểu:
- **Bản chất:** File `constants.py` được tạo ra để quản lý tập trung toàn bộ các thông báo lỗi và giá trị hằng số. Nhưng trong `NotFoundException`, code lại tự gõ nối chuỗi `f"{resource} with id '{resource_id}' not found"` mà bỏ qua hằng số `ERROR_USER_NOT_FOUND`. Các class exception khác như `BadRequestException` cũng đang viết cứng chuỗi `"Bad request"`.

### Code trước khi sửa (`app/core/exceptions.py`):
```python
class NotFoundException(AppException):
    def __init__(self, resource: str = "Resource", resource_id: int | str = "") -> None:
        detail = f"{resource} not found"
        if resource_id:
            detail = f"{resource} with id '{resource_id}' not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND, message=detail, error_code="NOT_FOUND"
        )


class BadRequestException(AppException):
    def __init__(self, message: str = "Bad request") -> None: ...
```

### Hướng giải quyết:
- Bổ sung các hằng số thông báo lỗi vào `app/core/constants.py`:
  - `ERROR_BAD_REQUEST`, `ERROR_PERMISSION_DENIED`, `ERROR_NOT_AUTHENTICATED`, `ERROR_RESOURCE_ALREADY_EXISTS`, `ERROR_RESOURCE_NOT_FOUND`, `ERROR_RESOURCE_WITH_ID_NOT_FOUND`, `ERROR_INTERNAL_SERVER`.
- Trong `NotFoundException`, ưu tiên dùng `ERROR_USER_NOT_FOUND` khi resource là "User", và dùng template hằng số cho các resource khác.
- Dùng hằng số làm giá trị mặc định cho toàn bộ các exception class.

### Code sau khi sửa (`app/core/exceptions.py`):
```python
class NotFoundException(AppException):
    """Resource not found (404)."""

    def __init__(self, resource: str = "Resource", resource_id: int | str = "") -> None:
        if resource.lower() == "user" and resource_id:
            detail = ERROR_USER_NOT_FOUND.format(user_id=resource_id)
        elif resource_id:
            detail = ERROR_RESOURCE_WITH_ID_NOT_FOUND.format(
                resource=resource, resource_id=resource_id
            )
        else:
            detail = ERROR_RESOURCE_NOT_FOUND.format(resource=resource)

        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            message=detail,
            error_code="NOT_FOUND",
        )


class BadRequestException(AppException):
    def __init__(self, message: str = ERROR_BAD_REQUEST) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=message,
            error_code="BAD_REQUEST",
        )
```

---

## 7. Lỗi 422 bị lệch định dạng JSON chung của hệ thống (`app/main.py`)

### Nhận xét nguyên văn của Giảng viên:
> *"In app/main.py: Lỗi 422 vẫn trả {"detail": [...]}, lệch format chung, thêm handler cho RequestValidationError."*

### Giải thích dễ hiểu:
- **Bản chất:** Mọi API trong dự án đều trả về cấu trúc lỗi chuẩn:
  ```json
  {
    "error": "ERROR_CODE",
    "message": "Nội dung lỗi",
    "path": "/api/v1/..."
  }
  ```
  Tuy nhiên, khi người dùng gửi sai kiểu dữ liệu, FastAPI mặc định tự động bắt và trả về `{"detail": [...]}`. Điều này làm phía Frontend nhận kết quả không đồng nhất, phải viết code xử lý riêng cho mã 422.

### Code trước khi sửa (`app/main.py`):
Chỉ bắt `AppException` và `Exception`, bỏ lọt `RequestValidationError`:
```python
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)
```

### Hướng giải quyết:
- Đăng ký thêm exception handler cho `RequestValidationError` từ `fastapi.exceptions`.
- Định dạng lại kết quả 422 sang chuẩn `{ "error": "VALIDATION_ERROR", "message": ..., "path": ..., "details": ... }`.

### Code sau khi sửa (`app/main.py`):
```python
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Format 422 validation errors to match the uniform API error format."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "path": str(request.url),
            "details": exc.errors(),
        },
    )


app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(IntegrityError, integrity_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)
```

---

## 8. Lỗi logic trong hàm Update Repository: Không xóa được giá trị Nullable (`app/repositories/base.py`)

### Nhận xét nguyên văn của Giảng viên:
> *"In app/repositories/base.py: Repo bỏ qua mọi None nên field nullable sau này ko xoá được, để service lo qua exclude_unset."*

### Giải thích dễ hiểu:
- **Bản chất:** Trong `BaseRepository.update`, dòng kiểm tra `if value is not None` vô tình làm mất tính năng: khi người dùng muốn xóa trắng một trường không bắt buộc (ví dụ: xóa ghi chú của task bằng cách gửi `{"description": null}`), thì hàm update thấy giá trị là `None` sẽ bỏ qua không cập nhật vào DB!
- **Nguyên lý phân tầng:** Tầng Repository chỉ đơn thuần thực thi cập nhật các trường được truyền vào. Việc phân biệt trường nào không được gửi lên (`unset`) và trường nào cố tình gửi `null` để xóa dữ liệu thuộc về trách nhiệm của tầng Service (thông qua `model_dump(exclude_unset=True)`).

### Code trước khi sửa (`app/repositories/base.py`):
```python
async def update(self, record_id: int, **kwargs: Any) -> ModelType | None:
    instance = await self.get_by_id(record_id)
    if instance is None:
        return None

    for field, value in kwargs.items():
        if value is not None and hasattr(instance, field):
            setattr(instance, field, value)

    await self.session.flush()
    await self.session.refresh(instance)
    return instance
```

### Hướng giải quyết:
- Xóa bỏ điều kiện `value is not None` trong `BaseRepository.update`. Chỉ cần kiểm tra `hasattr(instance, field)` là gán giá trị.

### Code sau khi sửa (`app/repositories/base.py`):
```python
async def update(self, record_id: int, **kwargs: Any) -> ModelType | None:
    instance = await self.get_by_id(record_id)
    if instance is None:
        return None

    for field, value in kwargs.items():
        if hasattr(instance, field):
            setattr(instance, field, value)

    await self.session.flush()
    await self.session.refresh(instance)
    return instance
```

---

## 9. Cú pháp `Annotated` thay vì bỏ qua linter `B008` (`pyproject.toml`)

### Nhận xét nguyên văn của Giảng viên:
> *"In pyproject.toml: Đừng ignore B008, chuyển sang Annotated."*

### Giải thích dễ hiểu:
- **Bản chất:** Linter Ruff có luật `B008` cảnh báo việc gọi hàm làm giá trị mặc định của tham số hàm (như `def endpoint(db = Depends(get_db))`). Trước đây ta cấu hình ignore `B008` để tránh cảnh báo. Nhưng trong chuẩn FastAPI hiện đại (từ bản 0.95+), cách viết chính thống là dùng `typing.Annotated`.

### Code trước khi sửa (`pyproject.toml`):
```toml
ignore = [
    "E501",
    "B008",
    "N802",
]
```

### Hướng giải quyết:
- Xóa `"B008"` khỏi mục `ignore` trong `pyproject.toml`.
- Chuyển toàn bộ tham số dùng `Depends` và `Query` sang dạng `Annotated`:
  - `SessionDep = Annotated[AsyncSession, Depends(get_db)]`
  - `UserServiceDep = Annotated[UserService, Depends(get_user_service)]`
  - `page: Annotated[int, Query(ge=1, ...)] = DEFAULT_PAGE`

### Code sau khi sửa (`pyproject.toml`):
```toml
ignore = [
    "E501",
    "N802",
]
```

---

## 10. Chuyển `get_user_service` về `dependencies.py` và Inject Repository

### Nhận xét nguyên văn của Giảng viên:
> *"In app/api/v1/endpoints/users.py: get_user_service chuyển về core/dependencies.py, inject repo qua Depends."*

### Giải thích dễ hiểu:
- **Bản chất:** Hàm khởi tạo `get_user_service` nằm trực tiếp trong file router `users.py` vi phạm nguyên tắc phân tách trách nhiệm (Separation of Concerns). Hơn nữa, `UserService` tự khởi tạo `UserRepository(session)` thay vì được inject thông qua dependency injection của FastAPI, làm hạn chế khả năng viết unit test mock repository.

### Code trước khi sửa (`app/api/v1/endpoints/users.py`):
```python
def get_user_service(
    session: AsyncSession = Depends(get_db),
) -> UserService:
    """Dependency: instantiate UserService with a DB session."""
    return UserService(session)
```

### Hướng giải quyết:
- Chuyển `get_user_repository` và `get_user_service` vào `app/core/dependencies.py`.
- `get_user_service` nhận `repo: UserRepoDep` qua `Depends(get_user_repository)`.
- Router chỉ cần khai báo tham số `service: UserServiceDep`.

### Code sau khi sửa (`app/core/dependencies.py`):
```python
SessionDep = Annotated[AsyncSession, Depends(get_db)]


def get_user_repository(session: SessionDep) -> UserRepository:
    """Dependency: instantiate UserRepository with a DB session."""
    return UserRepository(session)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_user_service(
    session: SessionDep,
    repo: UserRepoDep,
) -> UserService:
    """Dependency: instantiate UserService with an injected UserRepository."""
    return UserService(session, repo=repo)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
```

**Trong `app/api/v1/endpoints/users.py`:**
```python
@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    service: UserServiceDep,
) -> UserResponse:
    user = await service.create_user(data)
    return UserResponse.model_validate(user)
```

---

## 11. Dọn dẹp Schema thừa / không sử dụng (`app/schemas/common.py` & `user.py`)

### Nhận xét nguyên văn của Giảng viên:
> *"In app/schemas/common.py: PaginationParams khai mà ko dùng, router tự khai page/limit; ChangePassword cũng thừa."*

### Giải thích dễ hiểu:
- **Bản chất:** Class `PaginationParams` trong `common.py` được định nghĩa nhưng trong router lại khai báo tham số query rời rạc `page: int, limit: int`. Schema `ChangePassword` trong `user.py` thuộc phạm vi nghiệp vụ Đổi mật khẩu của Day 3 (Auth), không có endpoint nào ở Day 1 dùng tới. Đây là Dead Code (mã thừa) gây rác codebase.

### Code trước khi sửa:
```python
# app/schemas/common.py
class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")


# app/schemas/user.py
class ChangePassword(BaseSchema):
    current_password: str
    new_password: str = Field(...)
```

### Hướng giải quyết:
- Xóa bỏ class `PaginationParams` trong `app/schemas/common.py`.
- Xóa bỏ class `ChangePassword` trong `app/schemas/user.py` (chờ đến đúng Day 3 mới đưa vào).
- Các query params phân trang trong router dùng hằng số chuẩn `DEFAULT_PAGE`, `DEFAULT_LIMIT`, `MAX_LIMIT` từ `constants.py`.

---

## Bảng Tổng Kết Kiểm Tra Chất Lượng Mã Nguồn

| Công cụ kiểm tra | Trạng thái | Chi tiết |
| :--- | :--- | :--- |
| **`ruff check .`** | :white_check_mark: **Passed** | 0 lỗi linting, luật `B008` được tuân thủ nghiêm ngặt bằng `Annotated`. |
| **`ruff format --check .`** | :white_check_mark: **Passed** | Toàn bộ codebase được định dạng đồng nhất theo chuẩn PEP 8. |
| **Comment `#` trong code** | :white_check_mark: **Clean** | Không còn bất kỳ dòng comment `#` giải thích dư thừa nào trong mã nguồn. |
| **Bảo mật CORS & Fail-Fast** | :white_check_mark: **Secured** | Danh sách origin cụ thể trong Settings, buộc khai báo biến bảo mật trong `.env`. |
