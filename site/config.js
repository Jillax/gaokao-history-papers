window.SITE_CONFIG = {
  // 网站标题与副标题
  title: "新高考历史历年真题开放资料库",
  subtitle: "2015–2026 各省新高考历史试卷归档、检索与下载",

  // 静态资源（原卷/、雷达图/）的基础路径：
  // 1) 本地预览或 site/ 与 原卷/ 同域部署时，保持 ".." 或 "."
  // 2) 方案二（静态网站 + 对象存储）：填你的 OSS / COS / CDN 域名，例如：
  //    "https://your-bucket.oss-cn-hangzhou.aliyuncs.com"
  //    注意末尾不要加斜杠 /
  assetBaseUrl: "..",

  // 可选：你的 GitHub / Gitee 镜像仓库地址（留空则不显示仓库按钮）
  repoUrl: "https://github.com/Jillax/gaokao-history-papers",

  // 专题纪录片 / 视频资源（大文件托管于 GitHub Releases）
  videos: [
    {
      title: "《国家记忆》统编教材 · 第四集：以史育人（1080P 修复版）",
      meta: "MP4 高清视频 · 托管于 GitHub Releases · 历史教学与教研参考",
      size: "766.94 MB",
      url: "https://github.com/Jillax/gaokao-history-papers/releases/download/media-v1/_._._._1080P.mp4",
    },
  ],

  // 底部免责声明
  disclaimer:
    "本站所收录试卷均整理自各省教育考试院及公开网络资料，仅用于中学历史教学研究与个人学习交流。如有版权或勘误问题，请联系维护者处理。",
};
