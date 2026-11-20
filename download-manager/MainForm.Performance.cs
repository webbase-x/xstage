using System.Drawing;
using System.Windows.Forms;

namespace XStageDownloadManager;

public sealed partial class MainForm
{
    private void ConfigurePerformance()
    {
        using var dialog = new Form
        {
            Text = "ประสิทธิภาพและการจัดคิว · X-Stage",
            Width = 485, Height = 352,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterParent,
            MaximizeBox = false, MinimizeBox = false,
            BackColor = Color.White,
            Font = new Font("Segoe UI", 10)
        };
        var table = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, Padding = new Padding(20, 16, 20, 14),
            RowCount = 6, ColumnCount = 2
        };
        table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 70));
        table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 30));
        foreach (var height in new[] { 45, 45, 45, 45, 64, 45 })
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
        static Label Name(string value) => new()
        {
            Text = value, Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft
        };
        static NumericUpDown Number(int value, int max, int min = 1) => new()
        {
            Minimum = min, Maximum = max, Value = Math.Clamp(value, min, max),
            ThousandsSeparator = true,
            Dock = DockStyle.Fill, Margin = new Padding(3, 7, 3, 7)
        };
        var jobs = Number(_engine.MaxConcurrentJobs, 8);
        var perHost = Number(_engine.MaxJobsPerHost, 8);
        var speed = Number(_engine.GlobalLimitKib, 1_048_576, 0);
        table.Controls.Add(Name("งานดาวน์โหลดพร้อมกัน (1–8)"), 0, 0);
        table.Controls.Add(jobs, 1, 0);
        table.Controls.Add(Name("จำนวนงานพร้อมกันต่อเว็บไซต์ (1–8)"), 0, 1);
        table.Controls.Add(perHost, 1, 1);
        table.Controls.Add(Name("จำกัดความเร็ว HTTP รวม (KiB/s)"), 0, 2);
        table.Controls.Add(speed, 1, 2);
        table.Controls.Add(Name("0 = ไม่จำกัด · ขั้นต่ำ 64 KiB/s หากจำกัด"), 0, 3);
        var note = Name("การตั้งค่านี้ใช้กับไฟล์ HTTP/HTTPS โดยตรง\nการจำกัดความเร็วรวมยังไม่ครอบคลุมกระบวนการ yt-dlp");
        note.ForeColor = Color.FromArgb(90, 109, 132);
        table.Controls.Add(note, 0, 4);
        table.SetColumnSpan(note, 2);
        var controls = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft,
            WrapContents = false
        };
        var ok = new Button
        {
            Text = "บันทึก", Width = 112, Height = 35,
            DialogResult = DialogResult.OK
        };
        var cancel = new Button
        {
            Text = "ยกเลิก", Width = 92, Height = 35,
            DialogResult = DialogResult.Cancel
        };
        controls.Controls.Add(ok);
        controls.Controls.Add(cancel);
        table.Controls.Add(controls, 0, 5);
        table.SetColumnSpan(controls, 2);
        dialog.Controls.Add(table);
        dialog.AcceptButton = ok;
        dialog.CancelButton = cancel;
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            if (speed.Value is > 0 and < 64)
            {
                MessageBox.Show(this, "ความเร็วจำกัดต้องเป็น 0 หรืออย่างน้อย 64 KiB/s");
                return;
            }
            _engine.ConfigurePerformance((int)jobs.Value, (int)perHost.Value, (int)speed.Value);
            RefreshRows();
            _details.Text = "บันทึกการจัดคิวและจำกัดความเร็ว HTTP แล้ว";
        }
        catch (Exception ex) when (ex is IOException or ArgumentOutOfRangeException or
                                   Microsoft.Data.Sqlite.SqliteException)
        {
            MessageBox.Show(this, ex.Message, "บันทึกประสิทธิภาพไม่สำเร็จ",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void SetPriority(DownloadJob job, int priority)
    {
        try
        {
            _engine.SetJobPriority(job, priority);
            RefreshRows();
        }
        catch (Exception ex) when (ex is ArgumentOutOfRangeException or IOException)
        {
            MessageBox.Show(this, ex.Message, "ตั้งค่าลำดับความสำคัญไม่สำเร็จ");
        }
    }

    private void ConfigureFileSpeed(DownloadJob job)
    {
        using var dialog = new Form
        {
            Text = "จำกัดความเร็วไฟล์ · " + job.Name,
            Width = 420, Height = 205,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterParent,
            MaximizeBox = false, MinimizeBox = false, BackColor = Color.White
        };
        var label = new Label
        {
            Text = "จำกัดความเร็ว HTTP รายไฟล์ (KiB/s)\n0 = ไม่จำกัด · ขั้นต่ำ 64 KiB/s",
            Left = 20, Top = 17, Width = 360, Height = 52
        };
        var speed = new NumericUpDown
        {
            Minimum = 0, Maximum = 1_048_576,
            ThousandsSeparator = true, Left = 20, Top = 77, Width = 360,
            Value = job.FileSpeedLimitKib
        };
        var save = new Button
        {
            Text = "บันทึก", Left = 270, Top = 123,
            Width = 110, Height = 30, DialogResult = DialogResult.OK
        };
        dialog.Controls.AddRange(new Control[] { label, speed, save });
        dialog.AcceptButton = save;
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            _engine.SetFileSpeedLimit(job, (int)speed.Value);
            RefreshRows();
        }
        catch (Exception ex) when (ex is IOException or ArgumentOutOfRangeException)
        {
            MessageBox.Show(this, ex.Message, "กำหนดความเร็วไม่สำเร็จ");
        }
    }
}
