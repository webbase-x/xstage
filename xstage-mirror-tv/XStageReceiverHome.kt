package app.airshow.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.airshow.tv.Prefs
import app.airshow.tv.service.AirPlayService.ServerState
import app.airshow.tv.viewmodel.LocalNetworkAccess
import app.airshow.tv.viewmodel.MainViewModel

/**
 * A single-purpose receiver screen. No diagnostic panels, transport controls,
 * QR onboarding or start/stop actions on the everyday TV display.
 * The existing renderer takes the entire screen as soon as mirroring starts.
 */
@Composable
internal fun XStageReceiverHome(
    viewModel: MainViewModel,
    video: @Composable () -> Unit,
    onSettings: () -> Unit,
    onLocalNetwork: () -> Unit,
) {
    val state by viewModel.serverState.collectAsState()
    val connections by viewModel.connectionCount.collectAsState()
    val mirroringActive by viewModel.mirroringActive.collectAsState()
    val network by viewModel.localNetwork.collectAsState()
    val serverName by viewModel.pref(Prefs.SERVER_NAME).collectAsState()
    var editingName by remember { mutableStateOf(false) }

    LaunchedEffect(connections) {
        if (connections > 0) editingName = false
    }

    // Keep a live Surface attached until MainScreen transitions to fullscreen.
    // Never show labels or controls over the picture.
    if (mirroringActive && connections > 0) {
        Box(
            modifier = Modifier.fillMaxSize().background(Color.Black),
            contentAlignment = Alignment.Center
        ) { video() }
        return
    }

    val needsPermission = state != ServerState.RUNNING && network != LocalNetworkAccess.GRANTED
    val accent = when {
        needsPermission || state == ServerState.ERROR -> Color(0xFFFFC8A5)
        state == ServerState.RUNNING -> Color(0xFF83EEDC)
        else -> Color(0xFFBBCDE5)
    }
    val status = when {
        needsPermission -> "ต้องอนุญาตการเข้าถึงเครือข่าย"
        state == ServerState.ERROR -> "ตัวรับยังไม่พร้อม"
        connections > 0 -> "เชื่อมต่อแล้ว · กำลังรอภาพ"
        state == ServerState.RUNNING -> "พร้อมรับภาพ"
        else -> "กำลังเตรียมตัวรับภาพ"
    }

    Column(
        modifier = Modifier.fillMaxSize()
            .background(Color(0xFF08172B))
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 28.dp, vertical = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = "X-STAGE  /  MIRROR TV",
            style = MaterialTheme.typography.labelLarge,
            color = Color(0xFF93B7D1),
            fontWeight = FontWeight.Bold
        )
        Spacer(Modifier.height(16.dp))
        Text(
            text = serverName,
            style = MaterialTheme.typography.headlineLarge,
            color = Color.White,
            fontWeight = FontWeight.Black,
            textAlign = TextAlign.Center,
            maxLines = 3,
            overflow = TextOverflow.Ellipsis
        )
        Spacer(Modifier.height(7.dp))
        Text(
            text = "Version ${app.airshow.tv.BuildConfig.VERSION_NAME}  ·  Build ${app.airshow.tv.BuildConfig.VERSION_CODE}",
            style = MaterialTheme.typography.labelLarge,
            color = Color(0xFFACC9DF),
            textAlign = TextAlign.Center
        )
        Spacer(Modifier.height(20.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            Box(
                modifier = Modifier.size(11.dp).clip(CircleShape).background(accent)
            )
            Spacer(Modifier.width(10.dp))
            Text(
                text = status,
                style = MaterialTheme.typography.titleMedium,
                color = accent,
                fontWeight = FontWeight.SemiBold
            )
        }
        Spacer(Modifier.height(13.dp))
        if (needsPermission) {
            Text(
                text = "อนุญาตเครือข่ายเพื่อให้ iPhone หรือ iPad ค้นพบตัวรับ",
                style = MaterialTheme.typography.bodyMedium,
                color = Color(0xFFCFDEEF),
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(12.dp))
            Button(onClick = onLocalNetwork) { Text("อนุญาตเครือข่าย") }
        } else if (state == ServerState.ERROR) {
            Text(
                text = "โปรดตรวจสอบเครือข่าย แล้วเปิดแอปอีกครั้ง",
                style = MaterialTheme.typography.bodyMedium,
                color = Color(0xFFCFDEEF),
                textAlign = TextAlign.Center
            )
        } else if (connections == 0) {
            Text(
                text = "บน iPhone / iPad เปิด Screen Mirroring แล้วเลือกชื่อด้านบน",
                style = MaterialTheme.typography.bodyMedium,
                color = Color(0xFFCFDEEF),
                textAlign = TextAlign.Center
            )
        }
        if (editingName && connections == 0) {
            Spacer(Modifier.height(18.dp))
            Surface(
                modifier = Modifier.widthIn(max = 580.dp).fillMaxWidth(),
                shape = androidx.compose.foundation.shape.RoundedCornerShape(18.dp),
                color = Color(0xFF142A47)
            ) {
                Box(Modifier.padding(16.dp)) {
                    ReceiverNameEditor(viewModel, canEdit = true)
                }
            }
        }
        Spacer(Modifier.height(18.dp))
        Row(
            modifier = Modifier.fillMaxWidth().focusGroup(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (connections == 0) {
                TextButton(onClick = { editingName = !editingName }) {
                    Text(if (editingName) "ซ่อนการเปลี่ยนชื่อ" else "เปลี่ยนชื่อ", color = Color(0xFFBCE9FF))
                }
            }
            TextButton(onClick = onSettings) {
                Text("ตั้งค่า", color = Color(0xFFBCE9FF))
            }
        }
    }
}
