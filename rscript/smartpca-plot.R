#!/usr/bin/env Rscript
suppressWarnings(library(ggplot2))
suppressWarnings(library(scales))
suppressWarnings(library(stringr))

# get the command line arguments
args <- commandArgs(trailingOnly = TRUE)
pca1_file=args[1]
pca2_file=args[2]
pve_file=args[3]
pdf_file=args[4]
comp1=strtoi(args[5])
comp2=strtoi(args[6])
labeled=strtoi(args[7])

# TODO remove when done testing
# setwd("/Users/Evan/Dropbox/Code/ctvt")
# pca1_file = "smartpca/all-pops.merged_map.prj-DPC.calc.pca"
# pca2_file = "smartpca/all-pops.merged_map.prj-DPC.proj.pca"
# pve_file = "smartpca/all-pops.merged_map.prj-DPC.pve"
# pdf_file = "pdf/all-pops.merged_map.PCA.1.2.pdf"
# comp1=1
# comp2=2
# labeled=strtoi("0")

# get the percentage of variance each component explains
pve <- round(read.table(pve_file)[,1]*100, 1)

# get the metadata matrix for all the samples
info <- as.data.frame(read.table('pop_names.csv', sep = ",", quote = '"', header=TRUE, comment.char=""))

# read in the PCA data
t1 <- read.table(pca1_file)
t2 <- read.table(pca2_file)

names(t1)[1] <- "Code"
names(t2)[1] <- "Code"

# join the population types
t1meta <- merge(t1, info[c('Code','Type.Name','Colour','Shape','Order')], by = 'Code')
t2meta <- merge(t2, info[c('Code','Type.Name','Colour','Shape','Order')], by = 'Code')

# replace solid shapes with hollow ones for the projected populations
# see http://www.cookbook-r.com/Graphs/Shapes_and_line_types/
t2meta$Shape[t2meta$Shape==15]<-0
t2meta$Shape[t2meta$Shape==16]<-1
t2meta$Shape[t2meta$Shape==17]<-2
t2meta$Shape[t2meta$Shape==18]<-5

# join the two data frames
meta <- rbind(t1meta, t2meta)

# sort the matrix
meta <- meta[with(meta, order(Order)), ]

# set the order of the factors (as this determines the legend ordering)
meta[,'Type.Name'] <- factor(meta[,'Type.Name'], levels = unique(meta[,'Type.Name']))
# meta[,'Type.Name'] <- factor(meta[,'Type.Name'], levels = legend$Type.Name)

# setup the legend data
legend <- unique(meta[c('Type.Name','Colour','Shape', 'Order')])
legend$Colour <- sapply(legend$Colour, as.character)

alpha=c(1, 1, 1, 0.1, 1, 1, 1, 1, 1, 1, 1, 1)
pdf(file=pdf_file, width = 10, height = 7)

gg <- ggplot(meta, aes(meta[[comp1+2]], meta[[comp2+2]])) +
    aes(shape=factor(Type.Name)) +
    scale_shape_manual(values=legend$Shape) +
    scale_colour_manual(values=legend$Colour) +
    geom_point(aes(colour = factor(Type.Name)), size=4, alpha=1) +
    xlab(paste("PC", comp1, " (", pve[comp1], "%)", sep='')) +
    ylab(paste("PC", comp2, " (", pve[comp2], "%)", sep='')) +
    theme_bw() +
    # coord_fixed() +
    theme(legend.title=element_blank(), legend.key = element_blank()) +
    guides(colour = guide_legend(override.aes = list(size=4)))

if (labeled) {
  # label all the points
  gg <- gg + geom_text(aes(label=sub("^[^:]*:", "", meta$V2)), hjust=-.3, vjust=0, size=3)
}


# display the plot
gg

dev.off()
