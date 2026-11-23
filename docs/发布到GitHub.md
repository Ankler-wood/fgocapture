# 上传到 GitHub 分享：一步步做

> 目标：仓库里只放**源码 + 文档**，`FGOCapture.exe` 作为 **Release 附件**发布。
> 这样别人 git clone 得到的是可审查的代码，下载使用的人拿 exe，两不耽误。

---

## 0. 先想清楚三件事（很重要）

1. **绝对不能上传**（`.gitignore` 已挡住，但你上传前仍要确认一遍）：
   - `out\` —— 里面是你自己账号的 `toplogin_*.json`，等于账号数据；
   - `conf\` —— 里面有 `mitmproxy-ca.pem`（**根证书私钥**），泄露 = 任何人都能伪造证书骗过装了它的人。
2. **exe 别用 `git add` 塞进仓库**：33 MB 会让仓库永久变大，且每次更新都堆一份历史。放 Release。
   真要放仓库里，就用 Git LFS（`git lfs track "*.exe"`）。
3. **写清楚免责声明**（本仓库 README 已有）：只读抓包、不改客户端、不自动化、风险自担、
   不要外传导出的账号数据。

---

## 1. 装 Git（本机现在没有）

| 方式 | 说明 |
|---|---|
| 命令行 | 装 [Git for Windows](https://git-scm.com/download/win)，一路默认即可 |
| 图形界面 | 装 [GitHub Desktop](https://desktop.github.com/)，不用碰命令行 |

装完先配置身份（只需一次）：

```bat
git config --global user.name "你的名字"
git config --global user.email "你的邮箱@example.com"
```

---

## 2. 建仓库

1. 打开 https://github.com/new
2. Repository name：`fgocapture`（或你喜欢的）
3. **Public**（要分享）
4. 勾选项：
   - **Add a license → MIT** ✅（GitHub 会用你的账号名生成 `LICENSE`，建议勾）
   - Add a README ❌（本地已有）
   - Add .gitignore ❌（本地已有，且比模板多了 `out/`、`conf/` 两条关键规则）
5. Create repository

> 勾了 MIT 之后仓库会有一个 "Initial commit"，这是正常的；后面把文件传上去就是第二次提交。
> `repo\` 目录里**故意不放 LICENSE**，就是为了不覆盖 GitHub 用你名字生成的那份。

---

## 3. 上传代码（两种方式选一）

### 方式 A：命令行（推荐）

我已经把干净的仓库内容整理到了 `repo\` 目录（只含源码和文档，无 exe、无 out、无 conf）。
把它推到 GitHub：

```bat
cd /d C:\DeepSeekHarness\workplace\fgo-capture\repo
git init
git add .
git status                  :: 确认列表里没有 out/ conf/ *.exe
git commit -m "FGOCapture: FGO 抓包 -> Chaldea 导入文件（Windows 单文件工具）"
git branch -M main
git remote add origin https://github.com/<你的用户名>/fgocapture.git
git push -u origin main
```

### 方式 B：GitHub Desktop

1. Add local repository → 选 `repo` 目录（没有就点 "create repository here"）
2. 左侧确认没有 `out` / `conf` / `*.exe`
3. 填 Summary → Commit to main → Publish repository

### 方式 C：网页上传（不想装任何东西）

GitHub 仓库页 → **Add file → Upload files** → 把 `repo\` 里的内容拖进去 → Commit。
注意：网页不支持文件夹嵌套拖拽时，先建好一级目录再分别上传。

---

## 4. 发 Release（把 exe 放这里）

**命令行（装了 GitHub CLI 时）**：

```bat
gh release create v1.0.2 ^
  "FGOCapture.exe" "使用说明.txt" ^
  --title "FGOCapture v1.0.2" ^
  --notes "Windows 单文件版，双击即用。SHA-256 见下方。"
```

**网页**：仓库页右侧 **Releases → Draft a new release** → Tag `v1.0.2` →
把 `FGOCapture.exe` 和 `使用说明.txt` 拖进附件区 → 正文里贴上校验值：

```
SHA-256: <把 FGOCapture.exe 的哈希贴这里>
签名证书指纹: <FGOCapture.signature.txt 里的指纹>
```

发布后，你的分享链接就是：

```
https://github.com/<用户名>/fgocapture/releases/latest
```

别人只需要点这个链接下载两个文件，不用装 Python、不用编译。

---

## 5. 仓库里建议再补两样

- **README 顶部加截图/动图**（可选）：GitHub 页面有截图会让人更敢用。
- **Issues 模板 / 讨论区**：仓库 Settings → Features → 勾上 Issues（默认已开）。
- **Disclaimers 段**：README 里第「十一、安全与合规」已经写好，建议再在页面最上方放 3 行摘要。

---

## 6. 上传前自检清单

```bat
cd /d C:\DeepSeekHarness\workplace\fgo-capture\repo
git status --short
```

逐条确认：

- [ ] 列表里**没有** `out/`、`conf/`、`.venv/`
- [ ] 列表里**没有** `*.exe`（除非你确实想用 LFS 放仓库）
- [ ] 没有 `toplogin_*.json`、`auth.json`
- [ ] `README.md` 里的免责声明还在
- [ ] `LICENSE` 由 GitHub 生成（里面是你的账号名），想改成真名就网页上直接编辑
- [ ] 确认这版 exe 的 SHA-256 与 `使用说明.txt` 里写的一致（重新打包过就要重新生成）

---

## 7. 发布之后

- 想更新版本：改代码 → 跑 `build_exe.bat` → 新建 Release（别覆盖旧 tag）；
- 有人反馈杀软报毒：这是 PyInstaller/自解包 exe 的常见误报，在 Release 正文里说明
  「可自行用 `--verify` 核对哈希，或按 README 第二节从源码运行」；
- 有人要自己打包：README 的 `build_exe.bat` 已经写清楚流程；
- 中国大陆访问慢：可以同时把 Release 的两个文件传网盘，GitHub 页面上留个镜像链接。
