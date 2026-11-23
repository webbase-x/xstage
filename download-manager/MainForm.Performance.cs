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
            DialogResult = DialogResult.None
        };
        var cancel = new Button
        {
            Text = "ยกเลิก", Width = 92, Height = 35,
            DialogResult = DialogResult.Cancel
        };
        ok.Click += (_, _) =>
        {
            // Keep the settings dialog open if validation or SQLite persistence fails.
            dialog.DialogResult = DialogResult.None;
            if (speed.Value is > 0 and < 64)
            {
                MessageBox.Show(dialog, "ความเร็วจำกัดต้องเป็น 0 หรืออย่างน้อย 64 KiB/s",
                    "ค่าความเร็วไม่ถูกต้อง", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            try
            {
                _engine.ConfigurePerformance((int)jobs.Value, (int)perHost.Value, (int)speed.Value);
                RefreshRows();
                _details.Text = "บันทึกการจัดคิวและจำกัดความเร็ว HTTP แล้ว";
                dialog.DialogResult = DialogResult.OK;
            }
            catch (Exception ex) when (ex is IOException or ArgumentOutOfRangeException or
                                       Microsoft.Data.Sqlite.SqliteException)
            {
                MessageBox.Show(dialog, ex.Message, "บันทึกประสิทธิภาพไม่สำเร็จ",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        };
        controls.Controls.Add(ok);
        controls.Controls.Add(cancel);
        table.Controls.Add(controls, 0, 5);
        table.SetColumnSpan(controls, 2);
        dialog.Controls.Add(table);
        dialog.AcceptButton = ok;
        dialog.CancelButton = cancel;
        dialog.ShowDialog(this);
    }

    private void AssignJobQueue(DownloadJob job, string queueName)
    {
        try
        {
            _engine.SetJobQueue(job, queueName);
            RefreshRows();
            _details.Text = "ย้ายรายการไปยังคิว: " + job.QueueName;
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or
                                   Microsoft.Data.Sqlite.SqliteException)
        {
            MessageBox.Show(this, ex.Message, "จัดคิวไม่สำเร็จ",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void CreateJobQueue(DownloadJob job)
    {
        using var dialog = new Form
        {
            Text = "สร้างคิวดาวน์โหลด · X-Stage",
            Width = 420, Height = 205,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterParent,
            MaximizeBox = false, MinimizeBox = false,
            BackColor = Color.White,
            Font = new Font("Segoe UI", 10)
        };
        var label = new Label
        {
            Text = "ชื่อคิว (ไม่เกิน 64 ตัวอักษร)",
            Left = 20, Top = 18, Width = 360, Height = 25
        };
        var name = new TextBox
        {
            Left = 20, Top = 48, Width = 360, MaxLength = 64,
            Text = ""
        };
        var save = new Button
        {
            Text = "บันทึก", Left = 270, Top = 106, Width = 110,
            Height = 34, DialogResult = DialogResult.OK
        };
        var cancel = new Button
        {
            Text = "ยกเลิก", Left = 155, Top = 106, Width = 105,
            Height = 34, DialogResult = DialogResult.Cancel
        };
        dialog.Controls.AddRange(new Control[] { label, name, save, cancel });
        dialog.AcceptButton = save;
        dialog.CancelButton = cancel;
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        AssignJobQueue(job, name.Text);
    }

    private void RenameJobQueue(DownloadJob job)
    {
        if (!_engine.Jobs.Contains(job)) return;
        var previous = string.IsNullOrWhiteSpace(job.QueueName) ? "ทั่วไป" : job.QueueName;
        using var dialog = new Form
        {
            Text = "เปลี่ยนชื่อคิว · X-Stage",
            Width = 420, Height = 205,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterParent,
            MaximizeBox = false, MinimizeBox = false,
            BackColor = Color.White,
            Font = new Font("Segoe UI", 10)
        };
        var label = new Label
        {
            Text = "เปลี่ยนชื่อคิวทั้งกลุ่ม (ไม่เกิน 64 ตัวอักษร)",
            Left = 20, Top = 18, Width = 360, Height = 25
        };
        var name = new TextBox
        {
            Left = 20, Top = 48, Width = 360, MaxLength = 64,
            Text = previous
        };
        var save = new Button
        {
            Text = "บันทึก", Left = 270, Top = 106, Width = 110,
            Height = 34, DialogResult = DialogResult.OK
        };
        var cancel = new Button
        {
            Text = "ยกเลิก", Left = 155, Top = 106, Width = 105,
            Height = 34, DialogResult = DialogResult.Cancel
        };
        dialog.Controls.AddRange(new Control[] { label, name, save, cancel });
        dialog.AcceptButton = save;
        dialog.CancelButton = cancel;
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            var changed = _engine.RenameQueue(previous, name.Text);
            RefreshRows();
            _details.Text = $"เปลี่ยนชื่อคิว {previous} เป็น {name.Text.Trim()} · {changed} รายการ";
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or
                                   Microsoft.Data.Sqlite.SqliteException)
        {
            MessageBox.Show(this, ex.Message, "เปลี่ยนชื่อคิวไม่สำเร็จ",
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
            Value = Math.Clamp(job.FileSpeedLimitKib, 0, 1_048_576)
        };
        var save = new Button
        {
            Text = "บันทึก", Left = 270, Top = 123,
            Width = 110, Height = 30, DialogResult = DialogResult.None
        };
        var cancel = new Button
        {
            Text = "ยกเลิก", Left = 155, Top = 123,
            Width = 105, Height = 30, DialogResult = DialogResult.Cancel
        };
        save.Click += (_, _) =>
        {
            // A failed save must not dismiss the dialog or lose the user's input.
            dialog.DialogResult = DialogResult.None;
            if (speed.Value is > 0 and < 64)
            {
                MessageBox.Show(dialog, "ความเร็วจำกัดรายไฟล์ต้องเป็น 0 หรืออย่างน้อย 64 KiB/s",
                    "ค่าความเร็วไม่ถูกต้อง", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            try
            {
                _engine.SetFileSpeedLimit(job, (int)speed.Value);
                RefreshRows();
                dialog.DialogResult = DialogResult.OK;
            }
            catch (Exception ex) when (ex is IOException or ArgumentOutOfRangeException or
                                       Microsoft.Data.Sqlite.SqliteException)
            {
                MessageBox.Show(dialog, ex.Message, "กำหนดความเร็วไม่สำเร็จ",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        };
        dialog.Controls.AddRange(new Control[] { label, speed, save, cancel });
        dialog.AcceptButton = save;
        dialog.CancelButton = cancel;
        dialog.ShowDialog(this);
    }
}
