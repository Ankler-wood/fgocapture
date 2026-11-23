using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

// FGOCapture 单文件启动器（自带校验 + 自带教程）
//   --verify    打印本文件 SHA-256 / 内嵌载荷自校验 / 签名证书指纹，然后退出
//   --tutorial  打印内嵌的使用说明
//   正常启动    先校验内嵌 app.zip 的 SHA-256 是否与构建记录一致（防篡改），
//               再解包到 %LOCALAPPDATA%\FGOCapture\app-<长度>\ 并启动真正的程序
internal static class Launcher
{
    private const string ResourceName = "app.zip";
    private const string TutorialResource = "tutorial.txt";
    private const string MainExe = "FGOCapture.exe";

    [STAThread]
    private static int Main(string[] args)
    {
        try { Console.OutputEncoding = Encoding.UTF8; }
        catch { /* 忽略 */ }

        try
        {
            Assembly asm = Assembly.GetExecutingAssembly();
            string self = Path.GetFullPath(asm.Location);

            if (args.Length > 0 && (args[0] == "--tutorial" || args[0] == "--manual"))
            {
                return PrintTutorial(asm);
            }

            byte[] payload;
            using (Stream res = asm.GetManifestResourceStream(ResourceName))
            {
                if (res == null)
                {
                    Console.Error.WriteLine("[!] 启动器损坏：找不到内嵌数据");
                    return 3;
                }
                using (var ms = new MemoryStream())
                {
                    res.CopyTo(ms);
                    payload = ms.ToArray();
                }
            }

            string exeHash = Sha256File(self);
            string payloadHash = Sha256Bytes(payload);
            bool payloadOk = string.Equals(payloadHash, BuildInfo.AppZipSha256,
                                           StringComparison.OrdinalIgnoreCase);

            if (args.Length > 0 && (args[0] == "--verify" || args[0] == "-v"))
            {
                Console.WriteLine("FGOCapture 完整性信息");
                Console.WriteLine("  版本        : " + BuildInfo.Version);
                Console.WriteLine("  构建时间    : " + BuildInfo.BuildStamp);
                Console.WriteLine("  文件        : " + self);
                Console.WriteLine("  文件 SHA-256: " + exeHash);
                Console.WriteLine("  载荷 SHA-256: " + payloadHash);
                Console.WriteLine("  载荷自校验  : " + (payloadOk ? "通过（与构建记录一致）"
                                                    : "失败！文件被改动过，不要使用"));
                PrintSignatureInfo(self);
                Console.WriteLine();
                Console.WriteLine("  提示：本文件 SHA-256 应与发布者给你的「使用说明.txt」里的值一致。");
                return payloadOk ? 0 : 5;
            }

            if (!payloadOk)
            {
                Console.Error.WriteLine("[!] 完整性校验失败：内嵌数据与构建记录不一致。");
                Console.Error.WriteLine("    这个 exe 可能被人改过，请不要运行，去找发给你的人重新要一份。");
                return 5;
            }

            string baseDir = Environment.GetEnvironmentVariable("FGO_CAPTURE_HOME");
            if (string.IsNullOrEmpty(baseDir))
            {
                baseDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "FGOCapture");
            }
            string appDir = Path.Combine(baseDir, "app-" + payload.Length);
            string target = Path.Combine(appDir, MainExe);

            if (!File.Exists(target))
            {
                Directory.CreateDirectory(baseDir);
                string tmp = appDir + ".tmp" + Process.GetCurrentProcess().Id;
                if (Directory.Exists(tmp)) Directory.Delete(tmp, true);
                Directory.CreateDirectory(tmp);
                using (var zip = new ZipArchive(new MemoryStream(payload), ZipArchiveMode.Read))
                {
                    zip.ExtractToDirectory(tmp);
                }
                if (Directory.Exists(appDir)) Directory.Delete(appDir, true);
                Directory.Move(tmp, appDir);
            }

            var psi = new ProcessStartInfo(target)
            {
                UseShellExecute = false,
                WorkingDirectory = Path.GetDirectoryName(target),
                Arguments = JoinArgs(args),
            };
            // conf/ 和 out/ 生成在「用户放的 exe 所在目录」，而不是解包目录
            psi.EnvironmentVariables["FGO_APP_BASE"] = Path.GetDirectoryName(self);

            using (Process p = Process.Start(psi))
            {
                p.WaitForExit();
                return p.ExitCode;
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("[!] 启动失败：" + ex.Message);
            Console.Error.WriteLine(ex);
            return 4;
        }
    }

    private static int PrintTutorial(Assembly asm)
    {
        using (Stream res = asm.GetManifestResourceStream(TutorialResource))
        {
            if (res == null)
            {
                Console.WriteLine("（这个 exe 没有内嵌教程，请看同目录的「使用说明.txt」）");
                return 0;
            }
            using (var reader = new StreamReader(res, Encoding.UTF8))
            {
                Console.WriteLine(reader.ReadToEnd());
            }
        }
        return 0;
    }

    private static void PrintSignatureInfo(string exe)
    {
        string expected = BuildInfo.ExpectedSignerThumbprint ?? "";
        string signedThumb = "";
        string subject = "";
        try
        {
            X509Certificate cert = X509Certificate.CreateFromSignedFile(exe);
            signedThumb = cert.GetCertHashString() ?? "";
            subject = cert.Subject ?? "";
        }
        catch
        {
            // 未签名
        }

        if (expected.Length == 0 && signedThumb.Length == 0)
        {
            Console.WriteLine("  签名证书    : 未签名（只能靠上面的哈希判断）");
            return;
        }

        Console.WriteLine("  签名者      : " + (subject.Length > 0 ? subject : "（未签名）"));
        Console.WriteLine("  证书指纹    : " + (signedThumb.Length > 0 ? signedThumb : "（未签名）"));
        if (expected.Length == 0)
        {
            Console.WriteLine("  指纹对比    : （这一版构建记录里没有指纹）");
        }
        else if (signedThumb.Length == 0)
        {
            Console.WriteLine("  指纹对比    : 不一致！记录为 " + expected + "，但文件没有签名");
        }
        else
        {
            bool same = string.Equals(signedThumb, expected, StringComparison.OrdinalIgnoreCase);
            Console.WriteLine("  指纹对比    : " + (same
                ? "一致（" + expected + "）"
                : "不一致！记录为 " + expected + "，实际为 " + signedThumb));
        }
    }

    private static string Sha256Bytes(byte[] data)
    {
        using (var sha = SHA256.Create())
        {
            return BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
        }
    }

    private static string Sha256File(string path)
    {
        using (var sha = SHA256.Create())
        using (var fs = File.OpenRead(path))
        {
            return BitConverter.ToString(sha.ComputeHash(fs)).Replace("-", "").ToLowerInvariant();
        }
    }

    // 按 Windows 命令行规则把参数拼成字符串（.NET Framework 没有 ArgumentList）
    private static string JoinArgs(string[] args)
    {
        var sb = new StringBuilder();
        for (int i = 0; i < args.Length; i++)
        {
            if (i > 0) sb.Append(' ');
            sb.Append(Quote(args[i]));
        }
        return sb.ToString();
    }

    private static string Quote(string s)
    {
        if (s.Length > 0 && s.IndexOfAny(new[] { ' ', '\t', '"', '\n' }) < 0) return s;
        var sb = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char c in s)
        {
            if (c == '\\') { backslashes++; continue; }
            if (c == '"')
            {
                sb.Append('\\', backslashes * 2 + 1).Append('"');
            }
            else
            {
                sb.Append('\\', backslashes).Append(c);
            }
            backslashes = 0;
        }
        sb.Append('\\', backslashes * 2).Append('"');
        return sb.ToString();
    }
}
