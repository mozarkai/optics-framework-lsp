package ai.mozark.optics.lsp

import com.intellij.ide.util.PropertiesComponent
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.ReadAction
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.FileEditorManagerEvent
import com.intellij.openapi.fileEditor.FileEditorManagerListener
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.ComboBox
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.content.ContentFactory
import com.intellij.util.ui.JBUI
import java.awt.BorderLayout
import java.awt.Dimension
import java.awt.GridLayout
import java.awt.Graphics
import java.awt.RenderingHints
import java.awt.event.HierarchyEvent
import java.awt.image.BufferedImage
import java.io.ByteArrayInputStream
import java.util.Base64
import javax.imageio.ImageIO
import javax.swing.DefaultComboBoxModel
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.JToggleButton

class DeviceToolWindowFactory : ToolWindowFactory, DumbAware {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val content = ContentFactory.getInstance().createContent(DevicePanel(project), "", false)
        toolWindow.contentManager.addContent(content)
    }
}

private class Screen : JComponent() {
    var image: BufferedImage? = null
        set(value) {
            field = value
            revalidate()
            repaint()
        }
    var fit = true
        set(value) {
            field = value
            revalidate()
            repaint()
        }

    private fun natural(): Dimension? = image?.let { Dimension(it.width, it.height) }

    override fun getPreferredSize(): Dimension = if (fit) Dimension(0, 0) else natural() ?: Dimension(0, 0)

    override fun paintComponent(g: Graphics) {
        val natural = natural() ?: return
        val scale = if (fit) minOf(width.toDouble() / natural.width, height.toDouble() / natural.height) else 1.0
        val w = (natural.width * scale).toInt()
        val h = (natural.height * scale).toInt()
        val left = (width - w) / 2
        val top = (height - h) / 2
        g as java.awt.Graphics2D
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR)
        image?.let { g.drawImage(it, left, top, w, h, null) }
    }
}

private class DevicePanel(private val project: Project) : JPanel(BorderLayout()) {

    private val picker = ComboBox<Device>()
    private val note = JBLabel("Looking for devices…")
    private val screen = Screen()
    private val pause = JToggleButton("Pause")
    private val remembered = "optics.deviceView.last"

    @Volatile private var selected: Device? = null
    @Volatile private var lastSuite: String? = null

    // A hub screenshot takes seconds to ten, so it waits twice as long as it last took.
    @Volatile private var slowest = 0L
    private val poller = FramePoller({ 250L }) { frame() }
    private val pictures = FramePoller({ maxOf(10_000L, slowest * 2) }) { picture() }

    private fun remote() = selected?.id?.startsWith("remote:") == true

    private fun go() = if (remote()) pictures.start() else poller.start()

    private fun halt() {
        poller.stop()
        pictures.stop()
    }

    init {
        val refresh = JButton("Refresh")
        val zoom = JToggleButton("Actual size")
        refresh.addActionListener { relist() }
        pause.addActionListener { if (pause.isSelected) halt() else go() }
        zoom.addActionListener {
            screen.fit = !zoom.isSelected
            zoom.text = if (zoom.isSelected) "Fit" else "Actual size"
        }
        picker.addActionListener {
            selected = picker.selectedItem as? Device
            halt()
            screen.image = null
            selected?.let {
                PropertiesComponent.getInstance(project).setValue(remembered, it.id)
                tell(it)
            }
            if (!pause.isSelected && isShowing) go()
        }

        val buttons = JPanel(GridLayout(1, 3, 4, 0)).apply { add(refresh); add(pause); add(zoom) }
        val bar = JPanel(BorderLayout(0, 4)).apply {
            border = JBUI.Borders.empty(4)
            add(picker, BorderLayout.NORTH)
            add(buttons, BorderLayout.CENTER)
            add(note, BorderLayout.SOUTH)
        }
        add(bar, BorderLayout.NORTH)
        add(JBScrollPane(screen), BorderLayout.CENTER)

        project.messageBus.connect().subscribe(FileEditorManagerListener.FILE_EDITOR_MANAGER, object : FileEditorManagerListener {
            override fun selectionChanged(event: FileEditorManagerEvent) {
                if (isShowing && event.newFile?.extension?.lowercase() in OpticsLspDescriptor.SUFFIXES) relist()
            }
        })

        // Only while visible: each capture costs the emulator about a second.
        addHierarchyListener {
            if (it.changeFlags and HierarchyEvent.SHOWING_CHANGED.toLong() != 0L) {
                if (isShowing) { relist(); if (!pause.isSelected) go() } else halt()
            }
        }
    }

    private fun python(): java.nio.file.Path? {
        var result = OpticsPython.resolve()
        if (result is OpticsPython.Result.Unprobed) {
            OpticsPython.probeBlocking()
            result = OpticsPython.resolve()
        }
        return (result as? OpticsPython.Result.Ok)?.exe
    }

    // The language server is another process, and picks its device from this when nothing else does.
    private fun tell(device: Device) {
        if (device.id.startsWith("remote:")) return
        ApplicationManager.getApplication().executeOnPooledThread {
            val exe = python() ?: return@executeOnPooledThread
            runCatching { DeviceCommand.select(exe, device.id) }
        }
    }

    private fun say(text: String) = ApplicationManager.getApplication().invokeLater { note.text = text }

    // The panel has no editor of its own, so the suite is the last one looked at.
    private fun suite(): String? {
        val open = ReadAction.compute<String?, RuntimeException> {
            FileEditorManager.getInstance(project).selectedFiles
                .firstOrNull { it.extension?.lowercase() in OpticsLspDescriptor.SUFFIXES }
                ?.toNioPath()?.toUri()?.toString()
        }
        if (open != null) lastSuite = open
        return lastSuite
    }

    private fun relist() {
        ApplicationManager.getApplication().executeOnPooledThread {
            val exe = python() ?: return@executeOnPooledThread say(
                "No Python 3.12 or newer for the Optics server. Set one under Settings | Tools | Optics Framework."
            )
            // A hub device needs none of the local tools, so it is still offered.
            val listing = try {
                DeviceCommand.list(exe)
            } catch (error: Exception) {
                Listing(emptyList(), listOf(error.message ?: "Could not list devices"))
            }
            val hub = suite()?.let { runCatching { RemoteHub.device(project, it) }.getOrNull() }
            val devices = listing.devices + listOfNotNull(hub)
            val last = PropertiesComponent.getInstance(project).getValue(remembered)
            val pick = devices.firstOrNull { it.id == selected?.id }
                ?: devices.firstOrNull { it.id == last } ?: devices.firstOrNull()
            selected = pick
            ApplicationManager.getApplication().invokeLater {
                picker.model = DefaultComboBoxModel(devices.toTypedArray())
                picker.selectedItem = pick
                note.text = (if (devices.isEmpty()) listOf("No device found. Start an emulator or a simulator.") else emptyList<String>())
                    .plus(listing.notes).joinToString(" ")
            }
        }
    }

    private fun frame() {
        val device = selected ?: return
        val exe = python() ?: return
        try {
            val image = ImageIO.read(ByteArrayInputStream(DeviceCommand.capture(exe, device.id)))
            ApplicationManager.getApplication().invokeLater { screen.image = image; note.text = "" }
        } catch (error: Exception) {
            say(error.message ?: "Could not capture the screen")
            relist()
        }
    }

    private fun picture() {
        if (!remote()) return
        val began = System.currentTimeMillis()
        val shot = runCatching { RemoteHub.screenshot(project, suite() ?: return) }.getOrElse { return say(it.message ?: "Could not read the device") }
        slowest = System.currentTimeMillis() - began
        shot["error"]?.let { return say(it.asString) }
        val image = ImageIO.read(ByteArrayInputStream(Base64.getDecoder().decode(shot["png"].asString)))
        ApplicationManager.getApplication().invokeLater { screen.image = image }
    }
}
