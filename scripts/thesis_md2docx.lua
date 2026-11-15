-- 论文 Markdown → DOCX 的 pandoc 过滤器：
-- 1) 把 mermaid 代码块替换为"待重绘矢量图"的占位说明（Word 无法渲染 mermaid）；
-- 2) 丢弃以"说明："开头的元信息引语（正文不出现排版占位说明）。

local function starts_with(s, prefix)
  return s:sub(1, #prefix) == prefix
end

function CodeBlock(el)
  if el.classes and el.classes:includes("mermaid") then
    return pandoc.Para({ pandoc.Str("（此处为系统架构示意图，定稿时使用 Visio / draw.io 重绘为矢量图，并按图序编号。）") })
  end
end

function BlockQuote(el)
  if #el.content > 0 and el.content[1].t == "Para" then
    local text = pandoc.utils.stringify(el.content[1])
    if starts_with(text, "说明：") or starts_with(text, "说明:") then
      return {}
    end
  end
end
