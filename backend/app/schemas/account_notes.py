from pydantic import BaseModel, Field


class NoteMetrics(BaseModel):
    views: int | None = Field(None, description="阅读或播放量；null 表示平台未返回。")
    likes: int | None = Field(None, description="点赞数。")
    collects: int | None = Field(None, description="收藏数。")
    comments: int | None = Field(None, description="评论数。")
    shares: int | None = Field(None, description="分享数。")


class NoteAccountSummary(BaseModel):
    account_id: int = Field(description="用于查询和同步的账号标识；同号 PC / Creator 合并。")
    nickname: str
    avatar_url: str
    account_types: list[str]
    login_status: str
    total_notes: int = Field(description="本地保留的当前及历史笔记数量。")
    current_notes: int
    missing_notes: int = Field(description="本次完整同步未返回的历史记录数，不等于平台已删除。")
    totals: NoteMetrics = Field(description="当前笔记已知指标的合计；空值不计为零。")
    metric_note_counts: dict[str, int] = Field(description="每项合计中包含的已知指标笔记数。")
    sync_status: str = Field(description="never / syncing / success / partial / failed。")
    sync_source: str = Field(description="creator / pc，尚未同步时为空。")
    sync_message: str
    last_attempt_at: str | None
    synced_at: str | None = Field(description="最近成功时间，上海时区；失败时保留上次值。")


class NoteAccountList(BaseModel):
    items: list[NoteAccountSummary]


class ManagedNote(NoteMetrics):
    id: int = Field(description="本地记录标识。")
    note_id: str = Field(description="小红书笔记标识。")
    title: str
    cover_url: str
    note_url: str
    media_type: str = Field(description="image / video。")
    platform_status: str = Field(description="平台返回的提示文字；未返回时为空。")
    platform_status_code: str | None
    published_at: str | None = Field(description="平台发布时间，上海时区；未知时为null。")
    source: str
    in_latest_sync: bool
    synced_at: str


class ManagedNoteList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ManagedNote]
    account: NoteAccountSummary


class NoteSyncResult(BaseModel):
    synced_count: int = Field(description="本次从平台拉取并去重后的笔记数。")
    account: NoteAccountSummary
