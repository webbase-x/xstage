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
        _version.Text = args.Length == 9 ? $"รุ่น {_args[6]} · Build {_args[7]}" : "X-Stage Download Manager";
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
        Shown += (_, _) => BeginInvoke(new Action(StartInBackground));
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
            if (_args.Length != 9)
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
