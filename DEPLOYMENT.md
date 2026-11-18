# 开放试卷网站部署指南（国内静态网站 + 对象存储方案）

本项目已为你生成零构建依赖的静态网站（位于 `site/` 目录）与目录数据生成脚本（`scripts/build_site_data.py`）。

## 1. 本地预览

由于浏览器安全限制，直接双击 `site/index.html` 无法读取本地 JSON，请用任意本地 HTTP 服务打开。在项目根目录运行：

```bash
python -m http.server 8000
```

然后在浏览器访问：`http://localhost:8000/site/`

---

## 2. 线上部署（方案二：国内师生访问最稳）

### 方式 A：全部托管在阿里云 OSS / 腾讯云 COS（最省事，只用管理一个存储桶）

1. 在阿里云 OSS 或腾讯云 COS 新建一个 **标准存储 / 公共读** 的 Bucket（存储桶）。
2. 将以下目录原样上传到存储桶根目录：
   - `site/`
   - `原卷/`
   - `雷达图/`
3. 在存储桶设置中开启 **静态网站托管**（默认首页可设为 `site/index.html`，或将 `site/` 内的文件放到根目录并把 `site/config.js` 中的 `assetBaseUrl` 改为 `"."`）。
4. 绑定已备案的自定义域名并开启 CDN（阿里云/腾讯云新版本对象存储通常要求绑定自定义域名才能直接浏览器预览 HTML/PDF，否则会自动触发下载）。

### 方式 B：静态页面托管（EdgeOne Pages / Cloudflare Pages / Vercel）+ 对象存储（OSS/COS）

适合希望**网页免费托管、大文件走国内对象存储**的架构：

1. **上传试卷文件到对象存储**：
   - 将 `原卷/` 和 `雷达图/` 上传到阿里云 OSS 或腾讯云 COS（权限设为 **公共读**）。
   - 在对象存储的 **跨域设置（CORS）** 中添加规则：允许来源 `*`（或你的网站域名），允许方法 `GET`、`HEAD`，以便网页内弹窗正常预览 Markdown 等文件。
2. **修改网站资源地址**：
   - 打开 `site/config.js`，将 `assetBaseUrl` 改为你的对象存储/CDN 域名（末尾不要带 `/`）：
     ```js
     assetBaseUrl: "https://your-bucket.oss-cn-hangzhou.aliyuncs.com",
     ```
   - 如需展示开源仓库按钮，可填写 `repoUrl`（例如 Gitee 或 GitHub 仓库地址）。
3. **部署 `site/` 目录**：
   - 将 `site/` 目录直接拖拽或关联仓库部署到 **腾讯云 EdgeOne Pages**、**Cloudflare Pages** 或 **Vercel** 即可上线。

---

## 3. 日常更新流程

以后每当你在 [试卷目录.md](试卷目录.md) 或 [新高考历史卷 Top 20.md](新高考历史卷%20Top%2020.md) 中新增或修订了试卷，只需在项目根目录运行一次：

```bash
python scripts/build_site_data.py
```

脚本会自动重新生成 `site/data/catalog.json`（包含文件大小、格式标签与榜单信息），随后把更新后的 `site/data/catalog.json` 和新增的试卷文件同步上传即可。
