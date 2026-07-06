package it.osint.raven.openapi;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import it.osint.raven.AppInfo;
import it.osint.raven.controllers.SystemController;
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
import it.osint.raven.services.ConnectionState;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.lang.reflect.RecordComponent;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OpenApiDocumentationQualityGateTest {

    private static final List<Class<?>> API_CONTROLLERS = List.of(
            SystemController.class
    );

    private static final List<Class<?>> DOCUMENTED_DTOS = List.of(
            AppInfo.class,
            ConnectionProbe.class,
            ConnectionState.class,
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

    @Test
    void restApiControllersAreFullyDocumented() {
        for (Class<?> controller : API_CONTROLLERS) {
            assertNotNull(controller.getAnnotation(RestController.class), controller.getName() + " must be a REST controller");
            assertNotNull(controller.getAnnotation(Tag.class), controller.getName() + " must declare @Tag");
            assertTrue(isApiController(controller), controller.getName() + " must be mapped under /api/**");

            for (Method method : controller.getDeclaredMethods()) {
                if (isEndpointMethod(method)) {
                    assertNotNull(method.getAnnotation(Operation.class), method + " must declare @Operation");
                    assertNotNull(method.getAnnotation(ApiResponses.class), method + " must declare @ApiResponses");
                }
            }
        }
    }

    @Test
    void dtoTypesExposeSwaggerSchemas() {
        for (Class<?> dto : DOCUMENTED_DTOS) {
            assertNotNull(dto.getAnnotation(Schema.class), dto.getName() + " must declare class-level @Schema");

            if (dto.isEnum()) {
                continue;
            }

            if (dto.isRecord()) {
                for (RecordComponent component : dto.getRecordComponents()) {
                    assertTrue(
                            hasSchema(component),
                            dto.getName() + "." + component.getName() + " must declare @Schema"
                    );
                }
            } else {
                for (Field field : dto.getDeclaredFields()) {
                    if (!Modifier.isStatic(field.getModifiers())) {
                        assertNotNull(field.getAnnotation(Schema.class), dto.getName() + "." + field.getName() + " must declare @Schema");
                    }
                }
            }
        }
    }

    private static boolean isApiController(Class<?> controller) {
        RequestMapping mapping = controller.getAnnotation(RequestMapping.class);
        if (mapping == null) {
            return false;
        }
        for (String value : mapping.value()) {
            if (value.startsWith("/api")) {
                return true;
            }
        }
        for (String path : mapping.path()) {
            if (path.startsWith("/api")) {
                return true;
            }
        }
        return false;
    }

    private static boolean isEndpointMethod(Method method) {
        return method.isAnnotationPresent(GetMapping.class)
                || method.isAnnotationPresent(PostMapping.class)
                || method.isAnnotationPresent(PutMapping.class)
                || method.isAnnotationPresent(PatchMapping.class)
                || method.isAnnotationPresent(DeleteMapping.class);
    }

    private static boolean hasSchema(RecordComponent component) {
        if (component.getAnnotation(Schema.class) != null) {
            return true;
        }
        if (component.getAccessor().getAnnotation(Schema.class) != null) {
            return true;
        }
        try {
            Field field = component.getDeclaringRecord().getDeclaredField(component.getName());
            return field.getAnnotation(Schema.class) != null;
        } catch (NoSuchFieldException exception) {
            return false;
        }
    }
}
