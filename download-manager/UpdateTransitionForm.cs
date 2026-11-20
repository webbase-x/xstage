using System.Drawing;
using System.Threading;
using System.Windows.Forms;

namespace XStageDownloadManager;

/// <summary>
/// A small independent window, copied with the self-contained update helper,
/// stays on screen while the old EXE is replaced. The old app remains visible
/// until this window signals that it is ready to manage the transition.
/// </summary>
public sealed class UpdateTransitionForm : Form
{
    private readonly string[] _args;
    private readonly Label _message = new();
    private readonly Label _subtext = new();

    public UpdateTransitionForm(string[] args)
    {
        _args = args;
        Text = "X-Stage Download Manager — กำลังอัปเดต";
        Size = new Size(620, 205);
        MinimumSize = MaximumSize = Size;
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        ControlBox = false;
        ShowInTaskbar = true;
        TopMost = true;
        BackColor = Color.FromArgb(245, 249, 253);
        ForeColor = Color.FromArgb(23, 44, 76);
        Font = new Font("Segoe UI", 11);
        _message.Text = "เตรียมติดตั้งรุ่นใหม่ · กรุณาอย่าปิดหน้าต่างนี้";
        _message.Left = 22;
        _message.Top = 18;
        _message.Width = 565;
        _message.Height = 40;
        _message.Font = new Font("Segoe UI", 14, FontStyle.Bold);
        _subtext.Text = "โปรแกรมเดิมยังเปิดอยู่จนกว่าจะส่งต่องานอัปเดตสำเร็จ";
        _subtext.Left = 22;
        _subtext.Top = 66;
        _subtext.Width = 565;
        _subtext.Height = 40;
        var bar = new ProgressBar
        {
            Left = 22, Top = 120, Width = 565, Height = 22,
            Style = ProgressBarStyle.Marquee, MarqueeAnimationSpeed = 25
        };
        Controls.AddRange(new Control[] { _message, _subtext, bar });
        Shown += (_, _) => BeginInvoke(new Action(StartInBackground));
    }

    private void StartInBackground()
    {
        // Handshake: the original app does NOT close if the helper GUI failed
        // to start. Signal only after the window has been shown.
        try
        {
            if (_args.Length != 9)
                throw new ArgumentException("ข้อมูลโปรแกรมอัปเดตไม่ครบ");
            using var ready = EventWaitHandle.OpenExisting(_args[8]);
            ready.Set();
        }
        catch (Exception ex)
        {
            _message.Text = "ไม่สามารถเตรียมการอัปเดต";
            _subtext.Text = ex.Message;
            return;
        }

        _ = Task.Run(async () =>
        {
            int result = SelfUpdater.ApplyUpdateInHelper(_args, UpdateStatus);
            Environment.ExitCode = result;
            try
            {
                if (IsDisposed || !IsHandleCreated) return;
                BeginInvoke(new Action(() =>
                {
                    _message.Text = result == 0
                        ? "เปิดแอปรุ่นใหม่แล้ว"
                        : "อัปเดตไม่สำเร็จ · กำลังกลับไปยังแอปเดิม";
                    _subtext.Text = result == 0
                        ? "X-Stage Download Manager พร้อมใช้งาน"
                        : "ดูรายละเอียดที่ LocalAppData\\X-Stage\\Download Manager\\updates\\last-update.log";
                }));
                await Task.Delay(1400);
                if (!IsDisposed && IsHandleCreated)
                    BeginInvoke(new Action(Close));
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
                    _message.Text = status;
                    _subtext.Text = "กำลังจัดการอัปเดตอัตโนมัติ โปรดเปิดหน้าต่างนี้ไว้";
                }));
        }
        catch (InvalidOperationException) { }
    }
}
