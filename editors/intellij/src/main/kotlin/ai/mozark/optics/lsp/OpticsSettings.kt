package ai.mozark.optics.lsp

import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.components.service
import com.intellij.util.xmlb.XmlSerializerUtil

/** The one thing worth persisting: which interpreter to launch the server with. */
@Service(Service.Level.APP)
@State(name = "OpticsSettings", storages = [Storage("optics-framework-lsp.xml")])
class OpticsSettings : PersistentStateComponent<OpticsSettings> {

    @JvmField
    var pythonPath: String = ""

    override fun getState(): OpticsSettings = this

    override fun loadState(state: OpticsSettings) = XmlSerializerUtil.copyBean(state, this)

    companion object {
        fun getInstance(): OpticsSettings = service()
    }
}
