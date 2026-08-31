plugins {
    // Provisions the JDK the toolchain asks for, so a clone builds without a matching local JDK.
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}

rootProject.name = "optics-framework-lsp"
