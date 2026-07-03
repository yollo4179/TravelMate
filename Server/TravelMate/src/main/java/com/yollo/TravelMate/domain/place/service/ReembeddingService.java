package com.yollo.TravelMate.domain.place.service;

import java.util.ArrayList;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.domain.place.repository.PlaceJpaRepository;
import com.yollo.TravelMate.domain.place.repository.PlaceVectorRepository;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class ReembeddingService {

   
	
	private static final Logger log = LoggerFactory.getLogger(ReembeddingService.class);
	
    private static final int PAGE_SIZE = 64;

    private final PlaceVectorRepository placeRepository;
    private final EmbeddingClient  embeddingClient;
    
    public int reembedAll() {
        long afterId = 0;
        int updated = 0;

        while (true) {
            List<PlaceVectorRepository.PlaceText> page =
                    placeRepository.findAllForReembedding(afterId, PAGE_SIZE);
            if (page.isEmpty()) break;

            List<String> texts = page.stream()
                    .map(t -> t.name() + ". " + t.description())
                    .toList();

            List<float[]> embeddings = embeddingClient.embedBatch(texts);

            List<PlaceVectorRepository.PlaceEmbedding> updates = new ArrayList<>(page.size());
            for (int i = 0; i < page.size(); i++) {
                updates.add(new PlaceVectorRepository.PlaceEmbedding(
                        page.get(i).id(), embeddings.get(i)));
            }
            placeRepository.updateEmbeddings(updates);

            updated += page.size();
            afterId = page.get(page.size() - 1).id();
            log.info("재임베딩 진행: {}건 완료", updated);
        }
        return updated;
    }

}
