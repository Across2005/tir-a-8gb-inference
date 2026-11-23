# JSys problem paper（署名版）

本目录是 TIR-A 英文 problem paper 的**署名版**（author version）。

- 标题：*Problem: 8 GiB, 306–330 GB/s, 50/115 W: A Measured Boundary Map for Fully Resident LLM Inference*
- 作者：Yue Zheng（郑越），ORCID [0009-0001-6730-0935](https://orcid.org/0009-0001-6730-0935)，South China Normal University
- 预印本 DOI：[10.5281/zenodo.24456762](https://doi.org/10.5281/zenodo.24456762)（CC BY 4.0，2026-11-23，v1）
- 记录页：<https://zenodo.org/records/24456762>

## 与 Zenodo 上匿名版的关系

Zenodo 记录里挂的是**双盲匿名版**（投稿用，正文无作者、单位、邮箱、致谢、基金），
文件名 `JSys_Problem_Paper.pdf`。本目录的 `JSys_Problem_Paper_author_version.pdf`
是同一稿件的**署名版**：正文、数据、图表、参考文献与匿名版一致，**仅标题页**新增
作者、单位、ORCID、预印本 DOI 与一行版本说明（页数同为 18 页）。

投稿用的匿名源文件保持原样，未被本次发布改动。

## 引用格式

见同目录 [DOI.txt](DOI.txt)（含 BibTeX / plain / APA 三种）。

## 重建

本目录同时保留了可重建的 LaTeX 源：

```
main_signed.tex     # 署名版正文（相对匿名版只改标题页与 \author）
jsys.sty            # Journal of Systems Research 官方模板
plainurl.bst        # 参考文献样式
references.bib      # 参考文献库
fig_*.png           # 图 1–5
```

重建命令（MiKTeX）：

```bash
pdflatex -interaction=nonstopmode main_signed.tex
bibtex main_signed
pdflatex -interaction=nonstopmode main_signed.tex
pdflatex -interaction=nonstopmode main_signed.tex
```
