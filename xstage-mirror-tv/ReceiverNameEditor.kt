package app.airshow.tv.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import app.airshow.tv.Prefs
import app.airshow.tv.ReceiverNamePolicy
import app.airshow.tv.viewmodel.MainViewModel
import kotlinx.coroutines.launch

/**
 * Inline and scroll-into-view editor for Android TV: the virtual keyboard must
 * not obscure a modal dialog. Directional focus follows the visible controls.
 */
@Composable
internal fun ReceiverNameEditor(viewModel: MainViewModel, canEdit: Boolean) {
    val fullName by viewModel.pref(Prefs.SERVER_NAME).collectAsState()
    // Keep the input visible without requiring an extra click.
    val editOpen = true
    var suffixDraft by remember(fullName, editOpen) {
        mutableStateOf(ReceiverNamePolicy.suffixOf(fullName))
    }
    val namePreview = ReceiverNamePolicy.fromSuffix(suffixDraft)
    val valid = canEdit && ReceiverNamePolicy.isValid(namePreview)
    val keyboard = LocalSoftwareKeyboardController.current
    val scope = rememberCoroutineScope()
    val fieldBringIntoView = remember { BringIntoViewRequester() }
    val openFocus = remember { FocusRequester() }
    val fieldFocus = remember { FocusRequester() }
    val saveFocus = remember { FocusRequester() }
    val cancelFocus = remember { FocusRequester() }
    var openFocused by remember { mutableStateOf(false) }
    var saveFocused by remember { mutableStateOf(false) }
    var cancelFocused by remember { mutableStateOf(false) }

    fun saveName() {
        if (!valid) return
        viewModel.set(Prefs.SERVER_NAME, namePreview)
        keyboard?.hide()
        openFocus.requestFocus()
    }

    // On TV, opening a keyboard on initial render obscures the field.

    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(
            text = "ชื่อที่แสดงบน iPhone / iPad: $fullName",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface
        )
        OutlinedButton(
            onClick = {
                fieldFocus.requestFocus()
                scope.launch { kotlinx.coroutines.delay(280); fieldBringIntoView.bringIntoView() }
            },
            enabled = canEdit,
            border = BorderStroke(
                if (openFocused) 3.dp else 1.dp,
                if (openFocused) MaterialTheme.colorScheme.secondary
                else MaterialTheme.colorScheme.outline
            ),
            colors = ButtonDefaults.outlinedButtonColors(
                contentColor = MaterialTheme.colorScheme.onSurface
            ),
            modifier = Modifier
                .focusRequester(openFocus)
                .focusProperties { down = fieldFocus }
                .onFocusChanged { openFocused = it.isFocused }
        ) {
            Text("✎ เปลี่ยนชื่ออุปกรณ์ (ช่องพิมพ์ด้านล่าง)", fontWeight = FontWeight.SemiBold)
        }
        if (!canEdit) {
            Text(
                "เปลี่ยนชื่อได้เมื่อไม่มีอุปกรณ์กำลังเชื่อมต่อ เพื่อไม่ตัดภาพที่กำลังส่งอยู่",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        if (editOpen) {
            Surface(
                // IME padding is already applied by the parent screen.
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                color = MaterialTheme.colorScheme.surfaceContainerHigh,
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline)
            ) {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Text(
                        "ตั้งชื่อ X-Stage Mirror TV",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        "ชื่อหลัก (แก้ไขไม่ได้): ${ReceiverNamePolicy.PREFIX}",
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    OutlinedTextField(
                        value = suffixDraft,
                        onValueChange = { candidate ->
                            if (candidate.length <= ReceiverNamePolicy.MAX_SUFFIX_LENGTH &&
                                candidate.none { Character.isISOControl(it) }) {
                                suffixDraft = candidate
                            }
                        },
                        label = { Text("ชื่อห้อง / ชื่อเพิ่มเติม") },
                        placeholder = { Text("เช่น ห้องประชุม") },
                        singleLine = true,
                        textStyle = MaterialTheme.typography.bodyLarge.copy(
                            color = MaterialTheme.colorScheme.onSurface
                        ),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedTextColor = MaterialTheme.colorScheme.onSurface,
                            unfocusedTextColor = MaterialTheme.colorScheme.onSurface,
                            focusedContainerColor = MaterialTheme.colorScheme.surfaceContainer,
                            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainer,
                            focusedBorderColor = MaterialTheme.colorScheme.secondary,
                            unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                            focusedLabelColor = MaterialTheme.colorScheme.secondary,
                            cursorColor = MaterialTheme.colorScheme.secondary
                        ),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { saveName() }),
                        supportingText = {
                            Text("${suffixDraft.length}/${ReceiverNamePolicy.MAX_SUFFIX_LENGTH} ตัวอักษร")
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .bringIntoViewRequester(fieldBringIntoView)
                            .focusRequester(fieldFocus)
                            .focusProperties { up = openFocus; down = saveFocus }
                            .onFocusChanged {
                                if (it.isFocused) scope.launch {
                                    kotlinx.coroutines.delay(300)
                                    fieldBringIntoView.bringIntoView()
                                }
                            }
                            .onPreviewKeyEvent {
                                if ((it.key == Key.Enter || it.key == Key.NumPadEnter) && valid) {
                                    if (it.type == KeyEventType.KeyUp) saveName()
                                    true
                                } else false
                            }
                    )
                    Text(
                        "ชื่อที่จะปรากฏใน Screen Mirroring: $namePreview",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.secondary
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Button(
                            onClick = ::saveName,
                            enabled = valid,
                            border = if (saveFocused) BorderStroke(
                                3.dp, MaterialTheme.colorScheme.onSurface
                            ) else null,
                            modifier = Modifier
                                .weight(1f)
                                .focusRequester(saveFocus)
                                .focusProperties { up = fieldFocus; right = cancelFocus }
                                .onFocusChanged { saveFocused = it.isFocused }
                        ) {
                            Text("บันทึกชื่อ", fontWeight = FontWeight.Bold)
                        }
                        OutlinedButton(
                            onClick = {
                                keyboard?.hide()
                                suffixDraft = ReceiverNamePolicy.suffixOf(fullName)
                                openFocus.requestFocus()
                            },
                            border = BorderStroke(
                                if (cancelFocused) 3.dp else 1.dp,
                                if (cancelFocused) MaterialTheme.colorScheme.secondary
                                else MaterialTheme.colorScheme.outline
                            ),
                            colors = ButtonDefaults.outlinedButtonColors(
                                contentColor = MaterialTheme.colorScheme.onSurface
                            ),
                            modifier = Modifier
                                .weight(1f)
                                .focusRequester(cancelFocus)
                                .focusProperties { up = fieldFocus; left = saveFocus }
                                .onFocusChanged { cancelFocused = it.isFocused }
                        ) {
                            Text("ยกเลิก", fontWeight = FontWeight.SemiBold)
                        }
                    }
                }
            }
        }
    }
}
