package com.biomviewer.plugin

import com.intellij.openapi.fileTypes.FileType
import javax.swing.Icon

// ponytail: spike only -- no icon, no syntax highlighting, just enough to
// register the .biom extension and steer PyCharm away from its default
// binary-file viewer.
object BiomFileType : FileType {
    override fun getName() = "BIOM"
    override fun getDescription() = "BIOM sparse matrix file"
    override fun getDefaultExtension() = "biom"
    override fun getIcon(): Icon? = null
    override fun isBinary() = true
    override fun isReadOnly() = true
}
