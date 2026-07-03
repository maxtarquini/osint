package it.osint.raven.utils.article;

import com.fasterxml.jackson.databind.ObjectMapper;
import it.osint.raven.utils.OsintObjectMapper;

public final class ArticleObjectMapper {

    private ArticleObjectMapper() {
    }

    public static ObjectMapper create() {
        return OsintObjectMapper.create();
    }
}
