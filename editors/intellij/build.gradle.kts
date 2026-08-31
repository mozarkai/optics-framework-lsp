plugins {
    kotlin("jvm") version "2.2.0"
    id("org.jetbrains.intellij.platform") version "2.18.1"
}

kotlin { jvmToolchain(21) }

// Shared with the serverTest suite, which has no IntelliJ platform on its classpath. Anything in
// here must stay free of IntelliJ imports.
sourceSets.main { kotlin.srcDir("src/shared/kotlin") }

repositories {
    mavenCentral()
    intellijPlatform { defaultRepositories() }
}

dependencies {
    intellijPlatform {
        // Matches sinceBuild deliberately, so a newer API cannot be used by accident. Ultimate is
        // the distribution JetBrains documents for compiling against com.intellij.modules.lsp.
        intellijIdeaUltimate("2026.1.4")
        pluginVerifier()
    }
}

intellijPlatform {
    pluginConfiguration {
        version = providers.gradleProperty("pluginVersion")
        ideaVersion {
            // 261.26222 is 2026.1.4, where LspIntegrationProvider landed. Rename is consumed from
            // 2026.1.1, so this is the higher of the two floors. A bare "261" would let 2026.1 in.
            // See https://plugins.jetbrains.com/docs/intellij/language-server-protocol.html
            sinceBuild = "261.26222"
            // Unset, so a platform bump does not silently disable the plugin.
            untilBuild = provider { null }
        }
    }
    // Proves the plugin still loads on an IDE with no LSP module. Missing com.intellij.platform.lsp.*
    // classes are the known optional-dependency false positive — scope `ides {}`, do not weaken the code.
    pluginVerification { ides { recommended() } }
}

// Otherwise the release asset is a bare optics-framework-lsp.zip with no version in the name.
tasks.buildPlugin { archiveVersion = providers.gradleProperty("pluginVersion") }

// PYTHONPATH cannot point inside a jar, so the payload ships as a real directory next to it.
tasks.prepareSandbox {
    from(layout.projectDirectory.dir("../bundled/libs")) {
        into("${pluginName.get()}/bundled/libs")
        // Running the server writes bytecode back into the source tree, so exclude it here rather
        // than trusting whatever the last local run left behind.
        exclude("**/__pycache__/**")
    }
}

// `./gradlew runIde -PlspTrace` dumps the whole LSP conversation into the sandbox idea.log,
// which is the only way to see which files the client actually opened and what it asked for.
tasks.runIde {
    if (providers.gradleProperty("lspTrace").isPresent) {
        systemProperty("idea.log.debug.categories", "#com.intellij.platform.lsp")
        systemProperty("idea.is.internal", "true")
    }
}

// Not the `test` task: that one runs under the IDE's PathClassLoader as the system class loader,
// and this suite needs only the JDK to spawn the server as a subprocess.
testing.suites.register<JvmTestSuite>("serverTest") {
    useJUnitJupiter("6.1.3")
    sources { kotlin.srcDir("src/shared/kotlin") }
    dependencies {
        // The platform hands `main` its stdlib (see kotlin.stdlib.default.dependency in
        // gradle.properties); this suite has no platform dependency, so it needs its own.
        implementation("org.jetbrains.kotlin:kotlin-stdlib:2.2.0")
    }
    targets.all {
        testTask.configure {
            // The same two paths the plugin resolves at runtime.
            systemProperty(
                "optics.bundledLibs",
                layout.projectDirectory.dir("../bundled/libs").asFile.path,
            )
            systemProperty(
                "optics.fixture",
                layout.projectDirectory.dir("../fixtures/broken-suite").asFile.path,
            )
        }
    }
}

tasks.check { dependsOn(tasks.named("serverTest")) }
