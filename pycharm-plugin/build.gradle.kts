plugins {
    id("java")
    kotlin("jvm") version "2.3.0"
    id("org.jetbrains.intellij.platform") version "2.19.0"
}

group = "com.biomviewer"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        pycharm("2026.1")
    }
}

kotlin {
    jvmToolchain(21)
}

intellijPlatform {
    pluginConfiguration {
        name = "BiomViewer"
        version = "0.1.0"
    }
}
