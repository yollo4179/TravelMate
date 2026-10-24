package com.yollo.TravelMate.domain.place.service;

import java.util.ArrayList;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.data.internal.PlaceEmbeddingTarget;
import com.yollo.TravelMate.domain.place.data.internal.PlaceEmbeddingUpdate;
import com.yollo.TravelMate.domain.place.repository.PlaceEmbeddingRepository;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class ReembeddingService {

   
	
	private static final Logger log = LoggerFactory.getLogger(ReembeddingService.class);
	
    private static final int PAGE_SIZE = 64;

    private final PlaceEmbeddingRepository placeEmbeddingRepository;
    private final EmbeddingClient  embeddingClient;
    
    public int reembedAll() {
        long afterId = 0;
        int updated = 0;

        while (true) {
            List<PlaceEmbeddingTarget> page =
                    placeEmbeddingRepository.findTargets(afterId, PAGE_SIZE);
            if (page.isEmpty()) break;

            List<String> texts = page.stream()
                    .map(t -> t.name() + ". " + t.description())
                    .toList();

            List<float[]> embeddings = embeddingClient.embedBatch(texts);

            List<PlaceEmbeddingUpdate> updates = new ArrayList<>(page.size());
            for (int i = 0; i < page.size(); i++) {
                updates.add(new PlaceEmbeddingUpdate(
                        page.get(i).id(), embeddings.get(i)));
            }
            placeEmbeddingRepository.updateAll(updates);

            updated += page.size();
            afterId = page.get(page.size() - 1).id();
            log.info("재임베딩 진행: {}건 완료", updated);
        }
        return updated;
    }

}
