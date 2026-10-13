package ai.mozark.optics.lsp

import com.intellij.ide.util.PropertiesComponent
import com.intellij.openapi.application.ApplicationManager
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

    override fun getPreferredSize(): Dimension {
        val shot = image
        return if (shot == null || fit) Dimension(0, 0) else Dimension(shot.width, shot.height)
    }

    override fun paintComponent(g: Graphics) {
        val shot = image ?: return
        val scale = if (fit) minOf(width.toDouble() / shot.width, height.toDouble() / shot.height) else 1.0
        val w = (shot.width * scale).toInt()
        val h = (shot.height * scale).toInt()
        (g as java.awt.Graphics2D).setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR)
        g.drawImage(shot, (width - w) / 2, (height - h) / 2, w, h, null)
    }
}

private class DevicePanel(private val project: Project) : JPanel(BorderLayout()) {

    private val picker = ComboBox<Device>()
    private val note = JBLabel("Looking for devices…")
    private val screen = Screen()
    private val pause = JToggleButton("Pause")
    private val remembered = "optics.deviceView.last"

    @Volatile private var selected: Device? = null

    private val poller = FramePoller({ 1000 }) { frame() }

    init {
        val refresh = JButton("Refresh")
        val zoom = JToggleButton("Actual size")
        refresh.addActionListener { relist() }
        pause.addActionListener { if (pause.isSelected) poller.stop() else poller.start() }
        zoom.addActionListener {
            screen.fit = !zoom.isSelected
            zoom.text = if (zoom.isSelected) "Fit" else "Actual size"
        }
        picker.addActionListener { selected = picker.selectedItem as? Device
            selected?.let { PropertiesComponent.getInstance(project).setValue(remembered, it.id) } }

        // A FlowLayout row stays one line tall and clips the last buttons when narrow.
        val buttons = JPanel(GridLayout(1, 3, 4, 0)).apply { add(refresh); add(pause); add(zoom) }
        val bar = JPanel(BorderLayout(0, 4)).apply {
            border = JBUI.Borders.empty(4)
            add(picker, BorderLayout.NORTH)
            add(buttons, BorderLayout.CENTER)
            add(note, BorderLayout.SOUTH)
        }
        add(bar, BorderLayout.NORTH)
        add(JBScrollPane(screen), BorderLayout.CENTER)

        // Only while visible: each capture costs the emulator about a second.
        addHierarchyListener {
            if (it.changeFlags and HierarchyEvent.SHOWING_CHANGED.toLong() != 0L) {
                if (isShowing) { relist(); if (!pause.isSelected) poller.start() } else poller.stop()
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

    private fun say(text: String) = ApplicationManager.getApplication().invokeLater { note.text = text }

    private fun relist() {
        ApplicationManager.getApplication().executeOnPooledThread {
            val exe = python() ?: return@executeOnPooledThread say(
                "No Python 3.12 or newer for the Optics server. Set one under Settings | Tools | Optics Framework."
            )
            val listing = try {
                DeviceCommand.list(exe)
            } catch (error: Exception) {
                return@executeOnPooledThread say(error.message ?: "Could not list devices")
            }
            val last = PropertiesComponent.getInstance(project).getValue(remembered)
            val pick = listing.devices.firstOrNull { it.id == selected?.id }
                ?: listing.devices.firstOrNull { it.id == last } ?: listing.devices.firstOrNull()
            selected = pick
            ApplicationManager.getApplication().invokeLater {
                picker.model = DefaultComboBoxModel(listing.devices.toTypedArray())
                picker.selectedItem = pick
                note.text = (if (listing.devices.isEmpty()) listOf("No device found. Start an emulator or a simulator.") else emptyList<String>())
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
            // The device may have gone away or another one booted, so look again.
            relist()
        }
    }
}
