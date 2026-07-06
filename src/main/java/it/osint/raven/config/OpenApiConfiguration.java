package it.osint.raven.config;

import io.swagger.v3.core.converter.ModelConverters;
import io.swagger.v3.oas.annotations.OpenAPIDefinition;
import io.swagger.v3.oas.annotations.info.Contact;
import io.swagger.v3.oas.annotations.info.Info;
import io.swagger.v3.oas.annotations.info.License;
import io.swagger.v3.oas.annotations.servers.Server;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.media.Schema;
import it.osint.raven.AppInfo;
import it.osint.raven.dto.article.ArticleDto;
import it.osint.raven.dto.article.AssessmentDto;
import it.osint.raven.dto.article.ClaimDto;
import it.osint.raven.dto.article.ClaimType;
import it.osint.raven.dto.article.Confidence;
import it.osint.raven.dto.article.EmbeddingDto;
import it.osint.raven.dto.article.EntityDto;
import it.osint.raven.dto.article.EntityType;
import it.osint.raven.dto.article.EventDto;
import it.osint.raven.dto.article.EvidenceDto;
import it.osint.raven.dto.article.EvidenceType;
import it.osint.raven.dto.article.IntelligenceAssessmentDto;
import it.osint.raven.dto.article.LinksDto;
import it.osint.raven.dto.article.MetadataDto;
import it.osint.raven.dto.article.ProvenanceDto;
import it.osint.raven.dto.article.RelationshipDto;
import it.osint.raven.dto.article.TaxonomyDto;
import it.osint.raven.dto.source.AuthenticationDto;
import it.osint.raven.dto.source.AuthenticationType;
import it.osint.raven.dto.source.RawDocumentDto;
import it.osint.raven.dto.source.SourceDto;
import it.osint.raven.dto.source.SourceStatus;
import it.osint.raven.dto.source.SourceType;
import it.osint.raven.dto.system.ApiErrorResponse;
import it.osint.raven.dto.system.EndpointConfigurationDto;
import it.osint.raven.dto.system.QdrantConfigurationDto;
import it.osint.raven.dto.system.RavenConfigurationDto;
import it.osint.raven.services.ConnectionProbe;
import org.springdoc.core.customizers.OpenApiCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.List;
import java.util.Map;

@Configuration
@OpenAPIDefinition(
        info = @Info(
                title = "Raven OSINT API",
                version = "0.1.0-SNAPSHOT",
                description = "REST API for OSINT configuration, dependency status and workflow-oriented data contracts.",
                contact = @Contact(name = "Raven OSINT"),
                license = @License(name = "Internal")
        ),
        servers = {
                @Server(url = "/", description = "Current Raven API host")
        }
)
public class OpenApiConfiguration {

    private static final List<Class<?>> DOCUMENTED_DTOS = List.of(
            AppInfo.class,
            ConnectionProbe.class,
            ApiErrorResponse.class,
            EndpointConfigurationDto.class,
            QdrantConfigurationDto.class,
            RavenConfigurationDto.class,
            AuthenticationDto.class,
            AuthenticationType.class,
            SourceDto.class,
            SourceStatus.class,
            SourceType.class,
            RawDocumentDto.class,
            ArticleDto.class,
            AssessmentDto.class,
            ClaimDto.class,
            ClaimType.class,
            Confidence.class,
            EmbeddingDto.class,
            EntityDto.class,
            EntityType.class,
            EventDto.class,
            EvidenceDto.class,
            EvidenceType.class,
            IntelligenceAssessmentDto.class,
            LinksDto.class,
            MetadataDto.class,
            ProvenanceDto.class,
            RelationshipDto.class,
            TaxonomyDto.class
    );

    @Bean
    OpenAPI ravenOpenApi() {
        return new OpenAPI();
    }

    @Bean
    OpenApiCustomizer ravenDtoSchemaCustomizer() {
        return openApi -> DOCUMENTED_DTOS.forEach(dtoClass -> {
            Map<String, Schema> schemas = ModelConverters.getInstance().readAll(dtoClass);
            schemas.forEach(openApi::schema);
        });
    }
}
