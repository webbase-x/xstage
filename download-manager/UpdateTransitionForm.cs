using System.Drawing;
using System.Threading;
using System.Windows.Forms;

namespace XStageDownloadManager;

/// <summary>One independent progress window for the entire installation handoff.
/// The original application closes only after the readiness handshake.</summary>
public sealed class UpdateTransitionForm : Form
{
    private readonly string[] _args;
    private readonly Label _message = new();
    private readonly Label _subtext = new();
    private readonly Label _version = new();
    private readonly ProgressBar _bar = new();
    private readonly Button _dismiss = new();
    private bool _finished;

    public UpdateTransitionForm(string[] args)
    {
        _args = args;
        Text = "X-Stage Download Manager — อัปเดต";
        AutoScaleMode = AutoScaleMode.Font;
        ClientSize = new Size(580, 245);
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        ControlBox = false;
        ShowInTaskbar = true;
        TopMost = true;
        BackColor = Color.FromArgb(245, 249, 253);
        ForeColor = Color.FromArgb(23, 44, 76);
        Font = new Font("Segoe UI", 11);
        _version.SetBounds(20, 12, 540, 30);
        _version.Text = args.Length is 9 or 11 ? $"รุ่น {_args[6]} · Build {_args[7]}" : "X-Stage Download Manager";
        _message.SetBounds(20, 45, 540, 58);
        _message.Font = new Font("Segoe UI", 14, FontStyle.Bold);
        _subtext.SetBounds(20, 105, 540, 58);
        _bar.SetBounds(20, 172, 540, 20);
        _bar.Style = ProgressBarStyle.Marquee;
        _bar.MarqueeAnimationSpeed = 25;
        _dismiss.SetBounds(440, 202, 120, 32);
        _dismiss.Text = "ปิด";
        _dismiss.Visible = false;
        _dismiss.Click += (_, _) => Close();
        Controls.AddRange(new Control[] { _version, _message, _subtext, _bar, _dismiss });
        SetStage("ขั้นที่ 1/6 · เตรียมติดตั้ง", "ดาวน์โหลดและตรวจสอบไฟล์เบื้องต้นแล้ว · กำลังส่งต่องานจากแอปเดิม");
        FormClosing += (_, e) => { if (!_finished && e.CloseReason == CloseReason.UserClosing) e.Cancel = true; };
        // Position on the same monitor and center as the disposed download
        // window. Clamp to its working area if monitors changed during handoff.
        Load += (_, _) =>
        {
            if (args.Length == 11 && int.TryParse(args[9], out var x) && int.TryParse(args[10], out var y))
            {
                StartPosition = FormStartPosition.Manual;
                Location = CenterOnWorkingArea(new Point(x, y), Size);
            }
        };
        Shown += (_, _) => BeginInvoke(new Action(StartInBackground));
    }

    internal static Point CenterOnWorkingArea(Point center, Size size)
    {
        var area = Screen.FromPoint(center).WorkingArea;
        return new Point(
            (int)Math.Clamp((long)center.X - size.Width / 2, area.Left, Math.Max(area.Left, area.Right - size.Width)),
            (int)Math.Clamp((long)center.Y - size.Height / 2, area.Top, Math.Max(area.Top, area.Bottom - size.Height)));
    }

    private void SetStage(string message, string details)
    {
        _message.Text = message;
        _subtext.Text = details;
    }

    private void Finish(int result, string? detail = null)
    {
        _finished = true;
        Environment.ExitCode = result;
        _bar.MarqueeAnimationSpeed = 0;
        _bar.Style = ProgressBarStyle.Blocks;
        _bar.Value = result == 0 ? 100 : 0;
        TopMost = false;
        SetStage(result == 0 ? "ขั้นที่ 6/6 · ติดตั้งสำเร็จ" : "อัปเดตไม่สำเร็จ",
            detail ?? (result == 0 ? "ส่งคำสั่งเปิด X-Stage Download Manager รุ่นใหม่แล้ว" :
            "ดูรายละเอียดที่ LocalAppData\\X-Stage\\Download Manager\\updates\\last-update.log"));
        _dismiss.Visible = true;
    }

    private void StartInBackground()
    {
        try
        {
            if (_args.Length is not (9 or 11))
                throw new ArgumentException("ข้อมูลโปรแกรมอัปเดตไม่ครบ");
            using var ready = EventWaitHandle.OpenExisting(_args[8]);
            ready.Set();
        }
        catch (Exception ex)
        {
            // The parent retains its original UI. Do not leave an orphan
            // helper window behind if the readiness handshake failed.
            Finish(2, ex.Message);
            Close();
            return;
        }

        _ = Task.Run(async () =>
        {
            int result = SelfUpdater.ApplyUpdateInHelper(_args, UpdateStatus);
            try
            {
                if (IsDisposed || !IsHandleCreated) return;
                BeginInvoke(new Action(() => Finish(result)));
                if (result == 0)
                {
                    await Task.Delay(1200);
                    if (!IsDisposed && IsHandleCreated)
                        BeginInvoke(new Action(Close));
                }
            }
            catch (InvalidOperationException) { }
        });
    }

    private void UpdateStatus(string status)
    {
        try
        {
            if (!IsDisposed && IsHandleCreated)
                BeginInvoke(new Action(() =>
                {
                    if (!_finished)
                        SetStage(status, "กำลังจัดการอัปเดตอัตโนมัติ · โปรดเปิดหน้าต่างนี้ไว้");
                }));
        }
        catch (InvalidOperationException) { }
    }
}

/// <summary>First update window: consent, verified download, then close before
/// the second process is started. No installer can be launched here.</summary>
public sealed class UpdateDownloadForm : Form
{
    private readonly Label _message = new();
    private readonly Label _details = new();
    private readonly ProgressBar _bar = new();
    private readonly Button _begin = new();
    private readonly Button _cancelButton = new();
    private CancellationTokenSource? _cancel;
    public string? VerifiedSetup { get; private set; }
    public Exception? Error { get; private set; }
    public Point HandoffCenter { get; private set; }

    public UpdateDownloadForm(DownloadManagerRelease release, string activeNote)
    {
        Text = "X-Stage Download Manager — ดาวน์โหลดอัปเดต";
        AutoScaleMode = AutoScaleMode.Font;
        ClientSize = new Size(580, 245);
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        ControlBox = false;
        ShowInTaskbar = false;
        BackColor = Color.FromArgb(245, 249, 253);
        ForeColor = Color.FromArgb(23, 44, 76);
        Font = new Font("Segoe UI", 11);
        var version = new Label { Text = $"รุ่น {release.Version} · Build {release.Build}", AutoSize = false };
        version.SetBounds(20, 12, 540, 30);
        _message.SetBounds(20, 45, 540, 58);
        _message.Font = new Font("Segoe UI", 14, FontStyle.Bold);
        _message.Text = "ขั้นที่ 1/2 · ดาวน์โหลดและตรวจสอบไฟล์";
        _details.SetBounds(20, 105, 540, 58);
        _details.Text = $"ขนาด {release.Size / 1024.0 / 1024.0:0.0} MB · ตรวจ SHA-256 ก่อนติดตั้ง\n{activeNote}โปรแกรมจะเปิดใหม่หลังติดตั้ง";
        _bar.SetBounds(20, 172, 540, 20);
        _begin.Text = "อัปเดต";
        _begin.SetBounds(310, 202, 120, 32);
        _cancelButton.Text = "ยกเลิก";
        _cancelButton.SetBounds(440, 202, 120, 32);
        Controls.AddRange(new Control[] { version, _message, _details, _bar, _begin, _cancelButton });
        AcceptButton = _begin;
        _cancelButton.Click += (_, _) =>
        {
            if (_cancel is null) { DialogResult = DialogResult.Cancel; Close(); }
            else { _cancelButton.Enabled = false; _message.Text = "กำลังยกเลิก..."; _cancel.Cancel(); }
        };
        FormClosing += (_, e) =>
        {
            if (_cancel is not null && e.CloseReason == CloseReason.UserClosing)
            { e.Cancel = true; _cancel.Cancel(); }
        };
        _begin.Click += async (_, _) =>
        {
            if (_cancel is not null) return;
            using var cancellation = new CancellationTokenSource();
            _cancel = cancellation;
            _begin.Enabled = false;
            _message.Text = "ขั้นที่ 1/2 · กำลังดาวน์โหลด";
            var progress = new Progress<double>(percent =>
            {
                if (IsDisposed || _cancel is null || cancellation.IsCancellationRequested) return;
                _bar.Value = (int)Math.Clamp(percent, 0, 100);
                _message.Text = percent >= 100 ? "ตรวจสอบไฟล์สำเร็จ" : $"กำลังดาวน์โหลด · {percent:0.0}%";
            });
            try
            {
                VerifiedSetup = await SelfUpdater.DownloadVerifiedAsync(release, progress, cancellation.Token);
                HandoffCenter = new Point(Left + Width / 2, Top + Height / 2);
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
            catch (Exception ex) { Error = ex; }
            finally { _cancel = null; }
            if (!IsDisposed)
            {
                DialogResult = VerifiedSetup is not null ? DialogResult.OK : DialogResult.Cancel;
                Close();
            }
        };
    }
}
