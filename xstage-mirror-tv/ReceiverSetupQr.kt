package app.airshow.tv.ui

import android.graphics.Bitmap
import android.graphics.Color as AndroidColor
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import java.net.URLEncoder

/**
 * QR opens the iPhone setup guide with receiver name.
 * Apple does not allow a QR scan to start full-device Screen Mirroring silently.
 */
@Composable
internal fun ReceiverSetupQr(receiverName: String) {
    val qr = remember(receiverName) {
        runCatching {
            val url = "https://webbase-x.github.io/xstage/mirror-tv/?receiver=" +
                URLEncoder.encode(receiverName, "UTF-8")
            val matrix = QRCodeWriter().encode(
                url, BarcodeFormat.QR_CODE, 192, 192,
                mapOf(EncodeHintType.MARGIN to 1)
            )
            val bmp = Bitmap.createBitmap(matrix.width, matrix.height, Bitmap.Config.ARGB_8888)
            for (y in 0 until matrix.height) {
                for (x in 0 until matrix.width) {
                    bmp.setPixel(x, y,
                        if (matrix[x, y]) AndroidColor.BLACK else AndroidColor.WHITE)
                }
            }
            bmp.asImageBitmap()
        }.getOrNull()
    }
    if (qr != null) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Image(
                bitmap = qr,
                contentDescription = "QR code for X-Stage Mirror TV setup instructions",
                modifier = Modifier.size(128.dp)
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = "Scan QR for setup guide • เลือก Screen Mirroring บน iPhone",
                style = MaterialTheme.typography.labelSmall,
                textAlign = TextAlign.Center
            )
        }
    }
}
