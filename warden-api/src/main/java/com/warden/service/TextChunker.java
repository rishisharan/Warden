package com.warden.service;

import java.util.ArrayList;
import java.util.List;

/**
 * Splits document text into overlapping chunks. Simple paragraph-aware
 * splitter - good enough for the short fake documents Warden ingests; swap
 * for something smarter (sentence-boundary aware, token-counted) before
 * this touches real documents.
 */
public class TextChunker {

    private TextChunker() {
    }

    public static List<String> chunk(String text, int chunkSize, int overlap) {
        List<String> chunks = new ArrayList<>();
        String normalized = text.strip();
        if (normalized.isEmpty()) {
            return chunks;
        }
        if (normalized.length() <= chunkSize) {
            chunks.add(normalized);
            return chunks;
        }

        int start = 0;
        while (start < normalized.length()) {
            int end = Math.min(start + chunkSize, normalized.length());
            if (end < normalized.length()) {
                int breakPoint = normalized.lastIndexOf("\n\n", end);
                if (breakPoint <= start) {
                    breakPoint = normalized.lastIndexOf(". ", end);
                }
                if (breakPoint > start) {
                    end = breakPoint + 1;
                }
            }
            chunks.add(normalized.substring(start, end).strip());
            if (end >= normalized.length()) {
                break;
            }
            start = Math.max(end - overlap, start + 1);
        }
        return chunks;
    }
}
