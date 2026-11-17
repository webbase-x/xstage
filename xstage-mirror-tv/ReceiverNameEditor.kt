package app.airshow.tv.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import app.airshow.tv.Prefs
import app.airshow.tv.ReceiverNamePolicy
import app.airshow.tv.viewmodel.MainViewModel

/**
 * TV-remote focusable. The brand prefix is immutable. The active server
 * receives the saved pref through the existing restart-on-change mechanism.
 */
@Composable
internal fun ReceiverNameEditor(viewModel: MainViewModel, canEdit: Boolean) {
    val fullName by viewModel.pref(Prefs.SERVER_NAME).collectAsState()
    var editOpen by remember { mutableStateOf(false) }
    var suffixDraft by remember(fullName, editOpen) {
        mutableStateOf(ReceiverNamePolicy.suffixOf(fullName))
    }
    val namePreview = ReceiverNamePolicy.fromSuffix(suffixDraft)
    val keyboard = LocalSoftwareKeyboardController.current

    Column {
        Text(
            text = "ชื่อที่แสดงบน iPhone / iPad: $fullName",
            style = MaterialTheme.typography.bodyMedium
        )
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = { editOpen = true }, enabled = canEdit) {
            Text("✎ เปลี่ยนชื่ออุปกรณ์")
        }
        if (!canEdit) {
            Text(
                text = "เปลี่ยนชื่อได้เมื่อไม่มีอุปกรณ์กำลังเชื่อมต่อ เพื่อไม่ตัดภาพที่กำลังส่งอยู่",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }

    if (editOpen) {
        AlertDialog(
            onDismissRequest = { editOpen = false },
            title = { Text("ตั้งชื่อ X-Stage Mirror TV") },
            text = {
                Column {
                    Text("ชื่อหลัก (แก้ไขไม่ได้): ${ReceiverNamePolicy.PREFIX}")
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = suffixDraft,
                        onValueChange = { candidate ->
                            if (candidate.length <= ReceiverNamePolicy.MAX_SUFFIX_LENGTH &&
                                candidate.none { Character.isISOControl(it) }) {
                                suffixDraft = candidate
                            }
                        },
                        label = { Text("พิมพ์ชื่อเพิ่มเติมต่อท้าย") },
                        placeholder = { Text("เช่น ห้องประชุม หรือ TrueID ห้องนั่งเล่น") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { keyboard?.hide() }),
                        supportingText = {
                            Text("${suffixDraft.length}/${ReceiverNamePolicy.MAX_SUFFIX_LENGTH} ตัวอักษร")
                        },
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.height(12.dp))
                    Text(
                        text = "ชื่อที่จะปรากฏใน Screen Mirroring:\n$namePreview",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                    if (!canEdit) {
                        Spacer(Modifier.height(8.dp))
                        Text("กำลังเชื่อมต่ออยู่ กรุณาหยุดการส่งภาพก่อนบันทึก")
                    }
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        if (canEdit && ReceiverNamePolicy.isValid(namePreview)) {
                            viewModel.set(Prefs.SERVER_NAME, namePreview)
                            editOpen = false
                        }
                    },
                    enabled = canEdit && ReceiverNamePolicy.isValid(namePreview)
                ) { Text("บันทึกชื่อ") }
            },
            dismissButton = {
                TextButton(onClick = { editOpen = false }) { Text("ยกเลิก") }
            }
        )
    }
}
