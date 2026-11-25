import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { App as AntApp, Card, Empty, Input, List, Space, Tag } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { marked } from "marked";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { findChapterByPage, HELP_CHAPTERS } from "../content/help";
import type { HelpChapter } from "../content/help";
import { useI18n } from "../i18n";

/**
 * 帮助中心（补齐路线第一批 B1-15，顶栏全局入口）：
 * - 章节目录 + 全文内存检索（标题/正文子串命中高亮）；
 * - 「本页帮助」：/help?page={pathname} 打开时定位对应章节；无映射落目录。
 */

export default function HelpCenterPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [searchParams] = useSearchParams();
  const pageParam = searchParams.get("page") || "";
  const located = useMemo(() => (pageParam ? findChapterByPage(pageParam) : undefined), [pageParam]);
  const [selectedId, setSelectedId] = useState<string | null>(located?.id ?? null);
  const [keyword, setKeyword] = useState("");

  const chapters = HELP_CHAPTERS.slice().sort((left, right) => left.order - right.order);

  const searchHits = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    if (!query) return null;
    return chapters
      .map((chapter) => {
        const title = zh ? chapter.titleZh : chapter.titleEn;
        const titleHit = title.toLowerCase().includes(query);
        const bodyIndex = chapter.md.toLowerCase().indexOf(query);
        if (!titleHit && bodyIndex < 0) return null;
        const excerpt = bodyIndex >= 0
          ? chapter.md.slice(Math.max(0, bodyIndex - 40), bodyIndex + 80).replace(/\s+/g, " ")
          : title;
        return { chapter, titleHit, excerpt };
      })
      .filter((hit): hit is { chapter: HelpChapter; titleHit: boolean; excerpt: string } => hit !== null);
  }, [keyword, chapters, zh]);

  const selected = chapters.find((chapter) => chapter.id === selectedId) || located || null;
  const html = useMemo(
    () => (selected ? (marked.parse(selected.md, { async: false }) as string) : ""),
    [selected],
  );

  return (
    <AppLayout>
      <V2PageFrame section="portal" navKey="help_center" testId="v2-help-center">
        <PageHeading
          section="portal"
          navKey="help_center"
          desc={zh
            ? (located ? `本页帮助：${located.titleZh}` : "产品内帮助：章节目录、全文搜索与各页面操作指引。")
            : (located ? `Page help: ${located.titleEn}` : "In-product help: chapters, full-text search and page guides.")}
        />
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          <Input
            aria-label={zh ? "搜索帮助" : "Search help"}
            allowClear
            prefix={<SearchOutlined />}
            placeholder={zh ? "搜索标题与正文…" : "Search titles and contents…"}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          {searchHits !== null ? (
            <Card size="small">
              {searchHits.length === 0 ? (
                <Empty description={zh ? `未命中「${keyword}」` : `No match for "${keyword}"`} />
              ) : (
                <List
                  size="small"
                  dataSource={searchHits}
                  renderItem={({ chapter, titleHit, excerpt }) => (
                    <List.Item
                      style={{ cursor: "pointer" }}
                      onClick={() => { setSelectedId(chapter.id); setKeyword(""); message.success(zh ? `已打开「${chapter.titleZh}」` : `Opened "${chapter.titleEn}"`); }}
                    >
                      <List.Item.Meta
                        title={(zh ? chapter.titleZh : chapter.titleEn) + (titleHit ? "" : "")}
                        description={<span style={{ color: "var(--v2-dim)" }}>…{excerpt}…</span>}
                      />
                    </List.Item>
                  )}
                />
              )}
            </Card>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 16, alignItems: "start" }}>
              <Card size="small" title={zh ? "章节目录" : "Chapters"}>
                <List
                  size="small"
                  dataSource={chapters}
                  renderItem={(chapter) => (
                    <List.Item
                      style={{
                        cursor: "pointer",
                        background: selected?.id === chapter.id ? "var(--v2-hover, rgba(26,111,196,0.08))" : undefined,
                        borderRadius: 8,
                        paddingInline: 8,
                      }}
                      onClick={() => setSelectedId(chapter.id)}
                    >
                      <Space size={6}>
                        <Tag>{chapter.order}</Tag>
                        <span>{zh ? chapter.titleZh : chapter.titleEn}</span>
                      </Space>
                    </List.Item>
                  )}
                />
              </Card>
              <Card size="small">
                {selected ? (
                  <div
                    className="loop-manual-md"
                    style={{ maxHeight: "72vh", overflowY: "auto", lineHeight: 1.75, fontSize: 13.5 }}
                    // 手册为仓库内静态内容（同仓库随版本发布），非用户输入
                    dangerouslySetInnerHTML={{ __html: html }}
                  />
                ) : (
                  <Empty description={zh ? "从左侧目录选择章节；或用顶栏「帮助」按钮打开当前页面的指引" : "Pick a chapter; or use the topbar help button for the current page"} />
                )}
              </Card>
            </div>
          )}
        </Space>
      </V2PageFrame>
    </AppLayout>
  );
}
