import { FileTextOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Alert, Avatar, Button, Card, Col, Drawer, Empty, Image, Input, Row, Select, Space, Statistic, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { fetchAccountNotes, fetchNoteAccounts, syncAccountNotes } from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import type { AccountNotesQuery, AccountNotesResponse, ManagedAccountNote, NoteAccount, NoteMetric } from "../../../types/account-notes";

const { Text, Paragraph } = Typography;
const metricLabels: Record<NoteMetric, string> = { views: "阅读 / 播放", likes: "点赞", collects: "收藏", comments: "评论", shares: "分享" };
const metricKeys = Object.keys(metricLabels) as NoteMetric[];
const syncStates: Record<string, { label: string; color: string }> = {
  never: { label: "未同步", color: "default" }, syncing: { label: "同步中", color: "processing" },
  success: { label: "已同步", color: "green" }, partial: { label: "PC 同步", color: "gold" }, failed: { label: "同步失败", color: "red" },
};
const numberText = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString();
function errorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "请求失败，请稍后重试。";
}

export function XhsAccountNotesPage() {
  const [accounts, setAccounts] = useState<NoteAccount[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [loadingNotes, setLoadingNotes] = useState(false);
  const [data, setData] = useState<AccountNotesResponse | null>(null);
  const [query, setQuery] = useState<AccountNotesQuery>({ page: 1, page_size: 20, sort_by: "published_at", media_type: "all", presence: "all" });
  const [search, setSearch] = useState("");
  const [revision, setRevision] = useState(0);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [batching, setBatching] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detail, setDetail] = useState<ManagedAccountNote | null>(null);
  const noteRequest = useRef(0);
  const accountRequest = useRef(0);
  const syncBusy = useRef(false);
  const selected = accounts.find((account) => account.account_id === selectedId) ?? null;

  const loadAccounts = useCallback(async () => {
    const request = ++accountRequest.current;
    setLoadingAccounts(true);
    try {
      const result = await fetchNoteAccounts();
      if (request !== accountRequest.current) return;
      setAccounts(result.items);
      setSelectedId((current) => result.items.some((account) => account.account_id === current) ? current : result.items[0]?.account_id ?? null);
    } catch (reason) {
      if (request === accountRequest.current) setError(errorText(reason));
    } finally {
      if (request === accountRequest.current) setLoadingAccounts(false);
    }
  }, []);

  useEffect(() => { void loadAccounts(); return () => { accountRequest.current++; }; }, [loadAccounts]);
  useEffect(() => {
    const request = ++noteRequest.current;
    setData(null);
    if (selectedId == null) return;
    setLoadingNotes(true);
    void fetchAccountNotes(selectedId, query).then((result) => {
      if (request === noteRequest.current) setData(result);
    }).catch((reason) => {
      if (request === noteRequest.current) setError(errorText(reason));
    }).finally(() => { if (request === noteRequest.current) setLoadingNotes(false); });
    return () => { noteRequest.current++; };
  }, [selectedId, query, revision]);

  function changeQuery(patch: AccountNotesQuery) {
    setQuery((current) => ({ ...current, ...patch, page: 1 }));
  }

  function selectAccount(id: number) {
    setSelectedId(id);
    setData(null);
    setSearch("");
    setQuery({ page: 1, page_size: 20, sort_by: "published_at", media_type: "all", presence: "all" });
    setDetail(null);
  }

  async function runSync(all: boolean) {
    if (syncBusy.current) return;
    const targets = all ? accounts : accounts.filter((account) => account.account_id === selectedId);
    if (!targets.length) return;
    syncBusy.current = true;
    setBatching(all);
    setError(null);
    setNotice(null);
    let succeeded = 0;
    const failures: string[] = [];
    try {
      for (const [index, account] of targets.entries()) {
        setBusyId(account.account_id);
        setProgress(`正在同步 ${account.nickname || "小红书账号"}（${index + 1}/${targets.length}）`);
        try {
          const result = await syncAccountNotes(account.account_id);
          setAccounts((current) => current.map((item) => item.account_id === result.account.account_id ? result.account : item));
          succeeded++;
        } catch (reason) {
          failures.push(`${account.nickname || "小红书账号"}：${errorText(reason)}`);
        }
        setRevision((value) => value + 1);
      }
      setNotice(`同步结束：${succeeded} 个账号成功${failures.length ? `，${failures.length} 个账号失败，已保留其历史数据` : ""}。`);
      if (failures.length) setError(failures.join("；"));
      await loadAccounts();
    } finally {
      setBusyId(null);
      setBatching(false);
      setProgress("");
      syncBusy.current = false;
    }
  }

  const columns: ColumnsType<ManagedAccountNote> = [
    { title: "笔记", key: "note", width: 320, render: (_, note) => (
      <Space align="start">
        {note.cover_url ? <Image src={note.cover_url} width={56} height={72} style={{ objectFit: "cover", borderRadius: 6 }} referrerPolicy="no-referrer" /> : <Avatar shape="square" size={56} icon={<FileTextOutlined />} />}
        <Space direction="vertical" size={4}>
          <Button type="link" onClick={() => setDetail(note)} style={{ padding: 0, height: "auto", whiteSpace: "normal", textAlign: "left" }}>{note.title}</Button>
          <Space size={4} wrap><Tag>{note.media_type === "video" ? "视频" : "图文"}</Tag>{!note.in_latest_sync && <Tooltip title="本次完整同步未返回此笔记，保留历史记录，不据此判断是否已删除。"><Tag color="orange">本次未返回</Tag></Tooltip>}</Space>
        </Space>
      </Space>
    ) },
    { title: "发布时间", dataIndex: "published_at", width: 160, render: formatShanghaiTime },
    ...metricKeys.map((key) => ({ title: metricLabels[key], dataIndex: key, width: 110, render: numberText })),
    { title: "平台提示", key: "status", width: 180, render: (_, note) => note.platform_status || <Text type="secondary">未返回状态说明</Text> },
    { title: "操作", key: "action", width: 100, render: (_, note) => <a href={note.note_url} target="_blank" rel="noopener noreferrer">查看原文</a> },
  ];

  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <PageHeader eyebrow="XHS NOTES" title="笔记管理" description="按账号同步作品、查看互动数据。同一小红书号的 PC 与 Creator 登录合并展示。" action={<Space wrap>
      <Button icon={<ReloadOutlined />} loading={loadingAccounts} onClick={() => { void loadAccounts(); setRevision((value) => value + 1); }}>刷新数据</Button>
      <Button type="primary" icon={<SyncOutlined />} loading={batching} disabled={!!busyId || !accounts.length} onClick={() => void runSync(true)}>同步全部账号</Button>
    </Space>} />
    {error && <Alert type="error" title={error} showIcon closable onClose={() => setError(null)} />}
    {notice && <Alert type="success" title={notice} showIcon closable onClose={() => setNotice(null)} />}
    {progress && <Alert type="info" title={progress} showIcon />}
    <Row gutter={[16, 16]}>
      {accounts.map((account) => {
        const state = syncStates[account.sync_status] ?? syncStates.never;
        return <Col xs={24} md={12} xl={8} key={account.account_id}>
          <Card hoverable role="button" tabIndex={0} aria-label={`查看${account.nickname || "小红书账号"}的笔记`} aria-pressed={selectedId === account.account_id} onClick={() => selectAccount(account.account_id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectAccount(account.account_id); } }} style={{ borderColor: selectedId === account.account_id ? "#1668dc" : undefined, height: "100%" }}>
            <Space style={{ marginBottom: 12 }}><Avatar src={account.avatar_url || undefined} icon={<FileTextOutlined />} /> <Text strong>{account.nickname || "小红书账号"}</Text><Tag color={state.color}>{state.label}</Tag></Space>
            <div style={{ marginBottom: 8 }}>{account.account_types.map((type) => <Tag key={type}>{type === "creator" ? "Creator" : "PC"}</Tag>)}</div>
            <Text>已同步 {account.synced_at ? account.current_notes : "—"} 篇</Text>
            {account.missing_notes > 0 && <Text type="secondary"> · 历史未返回 {account.missing_notes} 篇</Text>}
            <div><Text type="secondary">最近同步：{formatShanghaiTime(account.synced_at)}</Text></div>
            {account.sync_status === "failed" && <Paragraph type="danger" style={{ marginTop: 8, marginBottom: 0 }}>{account.sync_message}</Paragraph>}
          </Card>
        </Col>;
      })}
    </Row>
    {!loadingAccounts && accounts.length === 0 && <Empty description="尚未绑定小红书账号"><Link to="/platforms/xhs/accounts"><Button type="primary">前往账号矩阵</Button></Link></Empty>}
    {selected && <>
      <Card title={`${selected.nickname || "小红书账号"} · 笔记情况`} extra={<Button type="primary" icon={<SyncOutlined />} loading={busyId === selectedId} disabled={busyId != null || batching} onClick={() => void runSync(false)}>同步当前账号</Button>}>
        <Row gutter={[16, 16]}>
          <Col xs={12} md={4}><Statistic title="当前笔记" value={selected.synced_at ? selected.current_notes : "—"} /></Col>
          {metricKeys.map((key) => <Col xs={12} md={4} key={key}><Tooltip title={`已返回该指标的 ${selected.metric_note_counts[key]} 篇当前笔记合计，缺失值不计为零。`}><Statistic title={metricLabels[key]} value={numberText(selected.totals[key])} /></Tooltip></Col>)}
        </Row>
        <Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0 }}>最近同步：{formatShanghaiTime(selected.synced_at)} · {selected.sync_source === "creator" ? "Creator 作品列表" : selected.sync_source === "pc" ? "PC 公开主页" : "尚未同步"}</Paragraph>
        {selected.sync_source === "pc" && <Alert type="warning" title={selected.sync_message} style={{ marginTop: 12 }} showIcon />}
      </Card>
      <Card>
        <Space wrap style={{ marginBottom: 16 }}>
          <Input.Search aria-label="搜索笔记标题" placeholder="搜索笔记标题" value={search} onChange={(event) => setSearch(event.target.value)} onSearch={() => changeQuery({ q: search })} allowClear style={{ width: 240 }} />
          <Select aria-label="笔记类型" value={query.media_type} style={{ width: 120 }} options={[{ value: "all", label: "全部类型" }, { value: "image", label: "图文" }, { value: "video", label: "视频" }]} onChange={(value) => changeQuery({ media_type: value })} />
          <Select aria-label="同步范围" value={query.presence} style={{ width: 150 }} options={[{ value: "all", label: "全部记录" }, { value: "current", label: "当前笔记" }, { value: "missing", label: "本次未返回" }]} onChange={(value) => changeQuery({ presence: value })} />
          <Select aria-label="笔记排序" value={query.sort_by} style={{ width: 150 }} options={[{ value: "published_at", label: "最新发布" }, ...metricKeys.map((key) => ({ value: key, label: `${metricLabels[key]}最多` }))]} onChange={(value) => changeQuery({ sort_by: value })} />
        </Space>
        <Table rowKey="id" columns={columns} dataSource={data?.items ?? []} loading={loadingNotes} scroll={{ x: 1350 }} locale={{ emptyText: selected.synced_at ? "没有符合条件的笔记" : "点击同步当前账号，获取笔记及互动数据" }} pagination={{ current: query.page, pageSize: query.page_size, total: data?.total ?? 0, showSizeChanger: true, showTotal: (total) => `共 ${total} 篇`, onChange: (page, page_size) => setQuery((current) => ({ ...current, page: current.page_size === page_size ? page : 1, page_size })) }} />
        <Text type="secondary">“—”表示平台未返回该指标。同步只读取笔记，不修改、删除或发布内容；历史未返回记录不等于平台已删除。</Text>
      </Card>
    </>}
    <Drawer title={detail?.title} open={!!detail} width={500} onClose={() => setDetail(null)}>
      {detail && <Space direction="vertical" size={16} style={{ width: "100%" }}>
        {detail.cover_url && <Image src={detail.cover_url} referrerPolicy="no-referrer" style={{ maxHeight: 320, objectFit: "contain" }} />}
        <Text>发布时间：{formatShanghaiTime(detail.published_at)}</Text>
        <Text>数据更新时间：{formatShanghaiTime(detail.synced_at)}</Text>
        {metricKeys.map((key) => <Text key={key}>{metricLabels[key]}：{numberText(detail[key])}</Text>)}
        <Text>平台提示：{detail.platform_status || "平台未返回状态说明"}</Text>
        <Button type="primary" href={detail.note_url} target="_blank" rel="noopener noreferrer">查看小红书原文</Button>
      </Space>}
    </Drawer>
  </div>;
}
