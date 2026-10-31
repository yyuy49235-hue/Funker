package app.funkerlitelab

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors

/** One screen. All logic lives in the Python engine (app/src/main/python); this only shows results. */
class MainActivity : Activity() {
    private val executor = Executors.newSingleThreadExecutor()
    private val pollExecutor = Executors.newSingleThreadExecutor()
    private val ui = Handler(Looper.getMainLooper())
    @Volatile private var busy = false

    private lateinit var modInput: EditText
    private lateinit var outInput: EditText
    private lateinit var permText: TextView
    private lateinit var permButton: Button
    private lateinit var modeGroup: RadioGroup
    private lateinit var rLossless: RadioButton
    private lateinit var rBalanced: RadioButton
    private lateinit var rAggressive: RadioButton
    private lateinit var resizeWarning: TextView
    private lateinit var progress: ProgressBar
    private lateinit var progressText: TextView
    private lateinit var resultView: TextView
    private lateinit var cancelButton: Button
    private val actionButtons = mutableListOf<Button>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        buildUi()
        refreshResizeControls()
    }

    override fun onResume() {
        super.onResume()
        val granted = hasAllFiles()
        permText.visibility = if (granted) View.GONE else View.VISIBLE
        permButton.visibility = if (granted) View.GONE else View.VISIBLE
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    private fun makeButton(textRes: Int, onClick: () -> Unit): Button {
        val b = Button(this)
        b.setText(textRes)
        b.setOnClickListener { onClick() }
        return b
    }

    private fun radio(textRes: Int): RadioButton {
        val r = RadioButton(this)
        r.id = View.generateViewId()
        r.setText(textRes)
        return r
    }

    private fun buildUi() {
        val root = LinearLayout(this)
        root.orientation = LinearLayout.VERTICAL
        root.setPadding(dp(12), dp(12), dp(12), dp(12))

        permButton = makeButton(R.string.btn_grant) { requestAccess() }
        permText = TextView(this)
        permText.setText(R.string.perm_needed)
        modInput = EditText(this)
        modInput.setHint(R.string.mod_hint)
        modInput.setText("/storage/emulated/0/.PsychEngine/mods/")
        modInput.setSingleLine(true)
        outInput = EditText(this)
        outInput.setHint(R.string.out_hint)
        outInput.setSingleLine(true)

        val modeTitle = TextView(this)
        modeTitle.setText(R.string.mode_title)
        modeTitle.setTypeface(Typeface.DEFAULT_BOLD)
        rLossless = radio(R.string.mode_lossless)
        rBalanced = radio(R.string.mode_balanced)
        rAggressive = radio(R.string.mode_aggressive)
        modeGroup = RadioGroup(this)
        modeGroup.addView(rLossless)
        modeGroup.addView(rBalanced)
        modeGroup.addView(rAggressive)
        rLossless.isChecked = true
        modeGroup.setOnCheckedChangeListener { _, _ -> refreshResizeControls() }

        resizeWarning = TextView(this)
        resizeWarning.setText(R.string.resize_warning)
        resizeWarning.visibility = View.GONE

        val inspectBtn = makeButton(R.string.btn_inspect) { run("inspect") }
        val validateBtn = makeButton(R.string.btn_validate) { runValidate() }
        val reportBtn = makeButton(R.string.btn_report) { run("report") }
        val scan = makeButton(R.string.btn_scan) { run("scan") }
        val atlas = makeButton(R.string.btn_atlas) { run("atlas") }
        val dry = makeButton(R.string.btn_dry) { run("dry") }
        val apply = makeButton(R.string.btn_apply) { confirmApply() }
        actionButtons.addAll(listOf(inspectBtn, validateBtn, reportBtn, scan, atlas, dry, apply))
        cancelButton = makeButton(R.string.btn_cancel) { cancelRun() }
        cancelButton.isEnabled = false

        progress = ProgressBar(this)
        progress.isIndeterminate = true
        progress.visibility = View.GONE
        progressText = TextView(this)
        progressText.setText(R.string.working)
        progressText.visibility = View.GONE

        resultView = TextView(this)
        resultView.setText(R.string.idle_hint)
        resultView.typeface = Typeface.MONOSPACE
        resultView.setTextIsSelectable(true)

        for (v in listOf<View>(permText, permButton, modInput, outInput, modeTitle, modeGroup,
            resizeWarning, inspectBtn, scan, atlas, dry, apply, validateBtn, reportBtn,
            cancelButton, progress, progressText, resultView)) root.addView(v)
        val scroll = ScrollView(this)
        scroll.addView(root)
        setContentView(scroll)
    }

    /** Only the warning depends on the mode. The resize factor is chosen automatically per image by the engine. */
    private fun refreshResizeControls() {
        resizeWarning.visibility = if (rLossless.isChecked) View.GONE else View.VISIBLE
    }

    private fun options(): String {
        val mode = if (rAggressive.isChecked) "aggressive" else if (rBalanced.isChecked) "balanced" else "lossless"
        val o = JSONObject()
        o.put("mode", mode)
        o.put("allow_resize", mode != "lossless") // choosing a resizing level is the explicit consent; apply asks again
        o.put("scale", "auto")
        o.put("target_pct", 45.0)
        o.put("detailed", true)
        return o.toString()
    }

    private fun hasAllFiles(): Boolean =
        if (Build.VERSION.SDK_INT >= 30) Environment.isExternalStorageManager()
        else checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED

    private fun requestAccess() {
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse("package:$packageName")))
            } catch (e: Exception) {
                startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
            }
        } else {
            requestPermissions(arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE,
                Manifest.permission.WRITE_EXTERNAL_STORAGE), 1)
        }
    }

    private fun confirmApply() {
        if (outInput.text.toString().trim().isEmpty()) {
            resultView.setText(R.string.need_output)
            return
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.confirm_title)
            .setMessage(if (rLossless.isChecked) R.string.confirm_msg else R.string.confirm_msg_resize)
            .setPositiveButton(R.string.yes) { _, _ -> run("apply") }
            .setNegativeButton(R.string.no, null)
            .show()
    }

    private fun setBusy(b: Boolean) {
        busy = b
        for (x in actionButtons) x.isEnabled = !b
        cancelButton.isEnabled = b
        val vis = if (b) View.VISIBLE else View.GONE
        progress.visibility = vis
        progressText.visibility = vis
        if (b) {
            progressText.setText(R.string.working)
            pollProgress()
        }
    }

    /** Shows real numbers from the engine (phase, file counts, current file). No fake percentage. */
    private fun pollProgress() {
        if (!busy) return
        pollExecutor.execute {
            val text = try {
                val j = JSONObject(Python.getInstance().getModule("bridge").callAttr("progress").toString())
                getString(R.string.progress_fmt, j.getString("phase"), j.getInt("done"), j.getInt("total"),
                    j.getString("current"), humanBytes(j.getLong("saved_bytes")))
            } catch (e: Exception) { null }
            ui.post { if (busy && text != null) progressText.text = text }
        }
        ui.postDelayed({ pollProgress() }, 700)
    }

    private fun humanBytes(n: Long): String = when {
        n >= 1L shl 20 -> String.format(Locale.US, "%.2f MB", n / 1048576.0)
        n >= 1L shl 10 -> String.format(Locale.US, "%.1f KB", n / 1024.0)
        else -> "$n B"
    }

    private fun cancelRun() {
        pollExecutor.execute {
            try { Python.getInstance().getModule("bridge").callAttr("cancel") } catch (e: Exception) { }
        }
    }

    private fun runValidate() {
        if (outInput.text.toString().trim().isEmpty()) {
            resultView.setText(R.string.need_output_validate)
            return
        }
        run("validate")
    }

    private fun shareText(text: String) {
        val send = Intent(Intent.ACTION_SEND)
        send.type = "text/plain"
        send.putExtra(Intent.EXTRA_TEXT, text)
        startActivity(Intent.createChooser(send, null))
    }

    private fun run(cmd: String) {
        if (!hasAllFiles()) {
            resultView.setText(R.string.perm_needed)
            return
        }
        val mod = modInput.text.toString().trim()
        val out = outInput.text.toString().trim()
        val opts = options()
        val ws = File(getExternalFilesDir(null) ?: filesDir, "workspace").absolutePath
        val lang = if (Locale.getDefault().language == "ar") "ar" else "en"
        setBusy(true)
        executor.execute {
            var share: String? = null
            val text = try {
                val raw = Python.getInstance().getModule("bridge")
                    .callAttr("run", cmd, mod, out, ws, lang, opts).toString()
                val j = JSONObject(raw)
                if (j.has("share")) share = j.getString("share")
                j.getString("text")
            } catch (e: Exception) {
                getString(R.string.error_prefix) + ": " + (e.message ?: e.toString())
            }
            runOnUiThread {
                resultView.text = text
                setBusy(false)
                share?.let { shareText(it) }
            }
        }
    }
}
