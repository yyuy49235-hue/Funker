package app.funkerlitelab

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.DocumentsContract
import android.provider.Settings
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.TextView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.Locale

/** Called from Python (bridge.py). Return false to cancel. */
fun interface ProgressSink {
    fun update(stage: String, done: Int, total: Int, name: String): Boolean
}

class MainActivity : Activity() {
    private val bgColor = Color.parseColor("#10151C")
    private val cardColor = Color.parseColor("#1A222D")
    private val accent = Color.parseColor("#4FD1C5")
    private val warn = Color.parseColor("#FFB84D")
    private val bad = Color.parseColor("#FF6B6B")
    private val txt = Color.parseColor("#F2F5F8")
    private val sub = Color.parseColor("#9AA7B5")

    private val reqMod = 1
    private val reqOut = 2
    private val reqAllFiles = 3

    private var modTree: Uri? = null
    private var outTree: Uri? = null
    @Volatile private var cancelled = false
    @Volatile private var running = false

    private lateinit var typedPath: EditText
    private lateinit var modStatus: TextView
    private lateinit var outStatus: TextView
    private lateinit var grantBtn: Button
    private lateinit var strengthGroup: RadioGroup
    private lateinit var startBtn: Button
    private lateinit var cancelBtn: Button
    private lateinit var progressCard: LinearLayout
    private lateinit var progressBar: ProgressBar
    private lateinit var stageText: TextView
    private lateinit var fileText: TextView
    private lateinit var resultCard: LinearLayout
    private lateinit var resultTitle: TextView
    private lateinit var resultBody: TextView

    private val strengths = listOf("light", "balanced", "strong", "maximum")

    // ---------------------------------------------------------------- UI

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = bgColor
        window.navigationBarColor = bgColor
        buildUi()
        restoreSavedFolders()
        refreshModStatus()
        refreshOutStatus()
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun rounded(color: Int, radius: Int = 14) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(radius).toFloat()
    }

    private fun card(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = rounded(cardColor)
        setPadding(dp(16), dp(14), dp(16), dp(16))
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            .apply { topMargin = dp(12) }
    }

    private fun heading(t: String) = TextView(this).apply {
        text = t; setTextColor(txt); textSize = 16f; typeface = Typeface.DEFAULT_BOLD
    }

    private fun body(t: String, color: Int = sub, size: Float = 13f) = TextView(this).apply {
        text = t; setTextColor(color); textSize = size
        setPadding(0, dp(6), 0, 0)
    }

    private fun button(label: String, primary: Boolean) = Button(this).apply {
        text = label; isAllCaps = false; textSize = 15f
        setTextColor(if (primary) bgColor else accent)
        background = if (primary) rounded(accent, 12) else GradientDrawable().apply {
            setColor(Color.TRANSPARENT); setStroke(dp(1), accent); cornerRadius = dp(12).toFloat()
        }
        stateListAnimator = null
        minimumHeight = dp(48)
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            .apply { topMargin = dp(10) }
    }

    private fun buildUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(20), dp(16), dp(28))
        }

        root.addView(TextView(this).apply {
            text = "Funker Lite Lab"; setTextColor(txt); textSize = 26f; typeface = Typeface.DEFAULT_BOLD
        })
        root.addView(body("Make FNF mods lighter for weak phones. Your original mod is never changed; the result is a new ZIP."))

        // 1. Mod
        val mod = card()
        mod.addView(heading("1  Mod folder"))
        val pick = button("Choose mod folder", true)
        pick.setOnClickListener { pickFolder(reqMod) }
        mod.addView(pick)
        mod.addView(body("or type / paste a path:"))
        typedPath = EditText(this).apply {
            hint = "/storage/emulated/0/.PsychEngine/mods/MyMod"
            setHintTextColor(Color.parseColor("#5E6B79")); setTextColor(txt); textSize = 14f
            setSingleLine(true)
            background = rounded(Color.parseColor("#232D3A"), 10)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            contentDescription = "Mod folder path"
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                override fun afterTextChanged(s: Editable?) {
                    if (!s.isNullOrBlank() && modTree != null) { modTree = null }
                    refreshModStatus()
                }
            })
        }
        mod.addView(typedPath)
        modStatus = body("")
        mod.addView(modStatus)
        grantBtn = button("Grant file access (needed for typed paths)", false)
        grantBtn.visibility = View.GONE
        grantBtn.setOnClickListener { requestAllFiles() }
        mod.addView(grantBtn)
        root.addView(mod)

        // 2. Output
        val out = card()
        out.addView(heading("2  Output folder"))
        val outBtn = button("Choose output folder", true)
        outBtn.setOnClickListener { pickFolder(reqOut) }
        out.addView(outBtn)
        outStatus = body("")
        out.addView(outStatus)
        root.addView(out)

        // 3. Strength
        val st = card()
        st.addView(heading("3  Compression strength"))
        st.addView(body("The app decides image by image what is safe. Strength only sets how far it may go."))
        strengthGroup = RadioGroup(this).apply { orientation = RadioGroup.VERTICAL }
        val labels = listOf(
            "Light\nLossless only. Image sizes never change.",
            "Balanced\nAlso shrinks very large character atlases to fit 2048 px.",
            "Strong\nCharacter atlases fit 1536 px. Smaller files.",
            "Maximum\nCharacter atlases fit 1024 px. Smallest, may look softer."
        )
        labels.forEachIndexed { i, l ->
            strengthGroup.addView(RadioButton(this).apply {
                id = 100 + i; text = l; setTextColor(txt); textSize = 14f
                setPadding(dp(8), dp(8), dp(4), dp(8))
                buttonTintList = android.content.res.ColorStateList.valueOf(accent)
            })
        }
        strengthGroup.check(101)
        st.addView(strengthGroup)
        st.addView(body("Images that cannot be resized safely (backgrounds, anything used by scripts) only get lossless compression, or are left alone."))
        root.addView(st)

        startBtn = button("Start optimizing", true)
        startBtn.setOnClickListener { startOptimize() }
        root.addView(startBtn)

        // Progress
        progressCard = card()
        progressCard.visibility = View.GONE
        stageText = heading("Working...")
        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = true
            progressTintList = android.content.res.ColorStateList.valueOf(accent)
            indeterminateTintList = android.content.res.ColorStateList.valueOf(accent)
        }
        fileText = body("")
        cancelBtn = button("Cancel", false)
        cancelBtn.setOnClickListener { cancelled = true; cancelBtn.isEnabled = false; stageText.text = "Cancelling..." }
        progressCard.addView(stageText); progressCard.addView(progressBar)
        progressCard.addView(fileText); progressCard.addView(cancelBtn)
        root.addView(progressCard)

        // Result
        resultCard = card()
        resultCard.visibility = View.GONE
        resultTitle = heading("")
        resultBody = body("", txt, 14f)
        resultCard.addView(resultTitle); resultCard.addView(resultBody)
        root.addView(resultCard)

        setContentView(ScrollView(this).apply {
            setBackgroundColor(bgColor); isFillViewport = true; addView(root)
        })
    }

    // ------------------------------------------------------- folder picking

    private fun pickFolder(req: Int) {
        if (running) return
        val i = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
            if (req == reqOut) addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        }
        try { startActivityForResult(i, req) } catch (e: Exception) {
            toast("No folder picker available on this device.")
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == reqAllFiles) { refreshModStatus(); return }
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) {
            toast("Selection cancelled - nothing changed.")
            return
        }
        val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or
            (if (requestCode == reqOut) Intent.FLAG_GRANT_WRITE_URI_PERMISSION else 0)
        try { contentResolver.takePersistableUriPermission(uri, flags) } catch (_: Exception) { /* still usable this session */ }
        val prefs = getSharedPreferences("flab", Context.MODE_PRIVATE)
        if (requestCode == reqMod) {
            modTree = uri
            typedPath.setText("")
            prefs.edit().putString("modTree", uri.toString()).apply()
            refreshModStatus()
        } else if (requestCode == reqOut) {
            outTree = uri
            prefs.edit().putString("outTree", uri.toString()).apply()
            refreshOutStatus()
        }
    }

    private fun restoreSavedFolders() {
        val prefs = getSharedPreferences("flab", Context.MODE_PRIVATE)
        val granted = contentResolver.persistedUriPermissions
        fun saved(key: String): Uri? = prefs.getString(key, null)?.let { Uri.parse(it) }?.takeIf { u ->
            granted.any { it.uri == u }
        }
        modTree = saved("modTree")
        outTree = saved("outTree")
    }

    private fun treeLabel(uri: Uri): String = Uri.decode(DocumentsContract.getTreeDocumentId(uri))

    private fun treeReadable(uri: Uri): Boolean = try {
        val id = DocumentsContract.getTreeDocumentId(uri)
        val kids = DocumentsContract.buildChildDocumentsUriUsingTree(uri, id)
        contentResolver.query(kids, arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID), null, null, null)?.use { true } ?: false
    } catch (e: Exception) { false }

    private fun hasAllFiles(): Boolean =
        if (Build.VERSION.SDK_INT >= 30) Environment.isExternalStorageManager() else true

    private fun requestAllFiles() {
        try {
            if (Build.VERSION.SDK_INT >= 30) {
                startActivityForResult(
                    Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName")), reqAllFiles)
            } else {
                requestPermissions(arrayOf(android.Manifest.permission.READ_EXTERNAL_STORAGE,
                    android.Manifest.permission.WRITE_EXTERNAL_STORAGE), 9)
            }
        } catch (e: Exception) {
            startActivityForResult(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION), reqAllFiles)
        }
    }

    override fun onResume() { super.onResume(); if (::modStatus.isInitialized) refreshModStatus() }

    private fun refreshModStatus() {
        val typed = typedPath.text.toString().trim()
        grantBtn.visibility = View.GONE
        when {
            typed.isNotEmpty() -> {
                val f = File(typed)
                if (f.isDirectory && f.canRead()) {
                    modStatus.text = "Using typed path (readable)."; modStatus.setTextColor(accent)
                } else {
                    modStatus.text = if (!hasAllFiles())
                        "Can't read this path. Grant file access below, or use \"Choose mod folder\"."
                    else "That path doesn't exist or isn't a readable folder."
                    modStatus.setTextColor(bad)
                    if (!hasAllFiles()) grantBtn.visibility = View.VISIBLE
                }
            }
            modTree != null -> {
                if (treeReadable(modTree!!)) {
                    modStatus.text = "Selected: " + treeLabel(modTree!!); modStatus.setTextColor(accent)
                } else {
                    modStatus.text = "Access to the selected folder was lost. Choose it again."; modStatus.setTextColor(bad)
                    modTree = null
                }
            }
            else -> { modStatus.text = "No mod selected yet."; modStatus.setTextColor(sub) }
        }
    }

    private fun refreshOutStatus() {
        val t = outTree
        if (t == null) { outStatus.text = "No output folder selected yet."; outStatus.setTextColor(sub); return }
        if (treeReadable(t)) {
            outStatus.text = "Selected: " + treeLabel(t) + "\nA new ZIP is saved here; nothing is overwritten."
            outStatus.setTextColor(accent)
        } else {
            outStatus.text = "Access to the output folder was lost. Choose it again."; outStatus.setTextColor(bad)
            outTree = null
        }
    }

    private fun toast(s: String) = android.widget.Toast.makeText(this, s, android.widget.Toast.LENGTH_SHORT).show()

    // ------------------------------------------------------------ processing

    private fun startOptimize() {
        if (running) return
        val typed = typedPath.text.toString().trim()
        val out = outTree
        if (typed.isEmpty() && modTree == null) { toast("Choose a mod folder first."); return }
        if (out == null) { toast("Choose an output folder first."); return }
        if (typed.isNotEmpty()) {
            val f = File(typed)
            if (!f.isDirectory || !f.canRead()) { refreshModStatus(); toast("The typed path is not readable."); return }
        } else if (!treeReadable(modTree!!)) { refreshModStatus(); return }

        // never write the result into the mod being read
        val outId = DocumentsContract.getTreeDocumentId(out)
        val inId = modTree?.let { DocumentsContract.getTreeDocumentId(it) }
        if (inId != null && (outId == inId || outId.startsWith("$inId/"))) {
            showError("The output folder is inside the mod folder. Choose a different output folder."); return
        }
        if (typed.isNotEmpty() && outId.startsWith("primary:")) {
            val outPath = File(Environment.getExternalStorageDirectory(), outId.removePrefix("primary:")).canonicalPath
            val inPath = File(typed).canonicalPath
            if (outPath == inPath || outPath.startsWith(inPath + File.separator)) {
                showError("The output folder is inside the mod folder. Choose a different output folder."); return
            }
        }

        val strength = strengths[(strengthGroup.checkedRadioButtonId - 100).coerceIn(0, 3)]
        val modName = if (typed.isNotEmpty()) File(typed).name else treeLabel(modTree!!).substringAfterLast('/').substringAfterLast(':')
        val srcTree = if (typed.isEmpty()) modTree else null

        running = true; cancelled = false
        setBusy(true)
        Thread {
            val work = File(cacheDir, "work-" + System.currentTimeMillis())
            try {
                work.mkdirs()
                val inputDir: File
                if (srcTree != null) {
                    inputDir = File(work, "in").also { it.mkdirs() }
                    ui("Copying mod into app storage", 0, 0, "")
                    var n = 0
                    copyTree(srcTree, inputDir) { name -> n++; if (n % 20 == 0) ui("Copying mod into app storage", 0, 0, "$n files  $name") }
                } else inputDir = File(typed)

                if (!Python.isStarted()) Python.start(AndroidPlatform(this))
                val zip = File(work, "result.zip")
                val sink = ProgressSink { stage, done, total, name -> ui(stage, done, total, name); !cancelled }
                val json = Python.getInstance().getModule("bridge")
                    .callAttr("run", inputDir.absolutePath, zip.absolutePath, strength, sink).toString()
                val r = JSONObject(json)
                if (!r.optBoolean("ok", false)) {
                    val msg = if (r.optBoolean("cancelled")) "Cancelled. Nothing was saved."
                    else r.optString("error").ifEmpty { "Validation failed: " + r.optJSONArray("problems") } + "\nNothing was saved; your mod is untouched."
                    runOnUiThread { showError(msg) }
                    return@Thread
                }
                ui("Saving ZIP to output folder", 0, 0, "")
                val outName = "$modName-optimized-$strength.zip"
                saveZip(out, zip, outName)
                runOnUiThread { showResult(r, outName, treeLabel(out)) }
            } catch (e: OutOfMemoryError) {
                runOnUiThread { showError("Ran out of memory on this device. Try a lighter mod or close other apps.") }
            } catch (e: IOException) {
                runOnUiThread { showError("File error: " + e.message + "\n(Is there enough free space?)") }
            } catch (e: Exception) {
                runOnUiThread { showError("Unexpected error: " + e.javaClass.simpleName + ": " + e.message) }
            } finally {
                work.deleteRecursively()
                running = false
                runOnUiThread { setBusy(false) }
            }
        }.start()
    }

    private fun ui(stage: String, done: Int, total: Int, name: String) {
        runOnUiThread {
            stageText.text = stage
            if (total > 0) {
                progressBar.isIndeterminate = false; progressBar.max = total; progressBar.progress = done
                fileText.text = "$done of $total\n$name"
            } else { progressBar.isIndeterminate = true; fileText.text = name }
        }
    }

    private fun setBusy(b: Boolean) {
        startBtn.isEnabled = !b
        progressCard.visibility = if (b) View.VISIBLE else View.GONE
        cancelBtn.isEnabled = true
        if (b) { resultCard.visibility = View.GONE; stageText.text = "Starting..."; fileText.text = ""; progressBar.isIndeterminate = true }
    }

    private fun safeName(n: String) = n.isNotEmpty() && n != "." && n != ".." && !n.contains('/') && !n.contains('\u0000')

    private fun copyTree(tree: Uri, dest: File, onFile: (String) -> Unit) {
        val rootId = DocumentsContract.getTreeDocumentId(tree)
        fun walk(docId: String, dir: File) {
            if (cancelled) throw IOException("Cancelled")
            val kidsUri = DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId)
            val items = ArrayList<Triple<String, String, String>>()
            contentResolver.query(kidsUri, arrayOf(
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE), null, null, null)?.use { c ->
                while (c.moveToNext()) items.add(Triple(c.getString(0), c.getString(1) ?: "", c.getString(2) ?: ""))
            } ?: throw IOException("Cannot list folder")
            for ((id, name, mime) in items) {
                if (!safeName(name)) throw IOException("Unsafe file name skipped: $name")
                val target = File(dir, name)
                if (mime == DocumentsContract.Document.MIME_TYPE_DIR) {
                    target.mkdirs(); walk(id, target)
                } else {
                    val u = DocumentsContract.buildDocumentUriUsingTree(tree, id)
                    contentResolver.openInputStream(u)?.use { ins -> target.outputStream().use { ins.copyTo(it, 64 * 1024) } }
                        ?: throw IOException("Cannot read $name")
                    onFile(name)
                }
            }
        }
        walk(rootId, dest)
    }

    private fun saveZip(tree: Uri, zip: File, name: String) {
        val parent = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val doc = DocumentsContract.createDocument(contentResolver, parent, "application/zip", name)
            ?: throw IOException("Could not create the output file in the chosen folder")
        try {
            contentResolver.openOutputStream(doc, "w")?.use { o -> zip.inputStream().use { it.copyTo(o, 64 * 1024) } }
                ?: throw IOException("Could not write to the output folder")
        } catch (e: Exception) {
            try { DocumentsContract.deleteDocument(contentResolver, doc) } catch (_: Exception) {}
            throw if (e is IOException) e else IOException(e.message)
        }
    }

    // --------------------------------------------------------------- results

    private fun fmt(b: Long): String = when {
        b >= 1L shl 30 -> String.format(Locale.US, "%.2f GB", b / 1073741824.0)
        b >= 1L shl 20 -> String.format(Locale.US, "%.1f MB", b / 1048576.0)
        b >= 1L shl 10 -> String.format(Locale.US, "%.0f KB", b / 1024.0)
        else -> "$b B"
    }

    private fun showError(msg: String) {
        resultCard.visibility = View.VISIBLE
        resultTitle.text = "Something went wrong"; resultTitle.setTextColor(bad)
        resultBody.text = msg
    }

    private fun showResult(r: JSONObject, outName: String, where: String) {
        val before = r.getLong("bytes_before"); val after = r.getLong("bytes_after")
        val diff = before - after
        val sb = StringBuilder()
        sb.append("Saved as $outName\nin $where\n\n")
        sb.append("Files in mod: ${r.getInt("files_total")}\n")
        sb.append("Images: ${r.getInt("images_total")}\n")
        sb.append("Optimized: ${r.getInt("optimized")}  (resized: ${r.getInt("resized")})\n")
        sb.append("Skipped: ${r.getInt("skipped")}\n")
        sb.append("Failed (original kept): ${r.getInt("failed")}\n")
        sb.append("XML/JSON files updated: ${r.getInt("refs_updated")}\n\n")
        sb.append("Before: ${fmt(before)}\nAfter: ${fmt(after)}\n")
        sb.append(if (diff >= 0) "Smaller by ${fmt(diff)}" else "Larger by ${fmt(-diff)}").append("\n")
        sb.append("(After = ZIP size; the ZIP also compresses non-image files.)\n")
        sb.append("Validation: passed (ZIP readable, every file present)\n")
        val d = r.getJSONArray("details")
        val reasons = LinkedHashMap<String, Int>()
        for (i in 0 until d.length()) {
            val o = d.getJSONObject(i)
            if (o.getString("action") == "skipped" || o.getString("action") == "failed" || o.getString("note").startsWith("not resized"))
                reasons.merge(o.getString("note").substringAfterLast("; "), 1, Int::plus)
        }
        if (reasons.isNotEmpty()) {
            sb.append("\nWhy some images were left as they are:\n")
            reasons.entries.sortedByDescending { it.value }.take(6).forEach { sb.append("- ${it.value} x ${it.key}\n") }
        }
        if (r.getInt("resized") > 0) sb.append("\nResized atlases were not tested in-game. Test the mod before deleting the original.")
        resultCard.visibility = View.VISIBLE
        resultTitle.text = "Done"; resultTitle.setTextColor(accent)
        resultBody.text = sb.toString()
    }
}
